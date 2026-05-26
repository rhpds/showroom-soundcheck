"""FastAPI application entry point."""

import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import API_KEY, CORS_ORIGINS, LOG_FORMAT, warn_default_credentials
from .database import async_session_factory
from .routes import check, groups, health, sessions
from .services import babylon_client, session_service
from .worker import checks_queue, orchestration_queue


def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    if LOG_FORMAT == "json":
        from pythonjsonlogger.json import JsonFormatter

        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
                defaults={"request_id": "-"},
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s",
                defaults={"request_id": "-"},
            )
        )
    root.addHandler(handler)


_configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    warn_default_credentials()
    await babylon_client._default_manager.init_clients_async()
    await orchestration_queue.connect()
    await checks_queue.connect()
    await session_service.cleanup_stale_sessions(async_session_factory)
    logger.info("Soundcheck API started")
    yield
    for q in (orchestration_queue, checks_queue):
        try:
            await q.disconnect()
        except Exception:
            logger.debug("Queue disconnect failed (Redis may already be down)")
    await babylon_client._default_manager.close_clients()
    logger.info("Soundcheck API shut down")


app = FastAPI(
    title="Showroom Soundcheck",
    description="Session-based health check tool for showroom environments",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9._:/-]{1,128}$")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request ID (accept from client or generate) and return it in the response."""
    raw = request.headers.get("X-Request-ID", "")
    request_id = raw if _REQUEST_ID_RE.match(raw) else str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    """Require X-API-Key header on mutating requests when API_KEY is set."""
    if API_KEY and request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-API-Key") != API_KEY:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key"},
        )
    return await call_next(request)


app.include_router(sessions.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(check.router, prefix="/api")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "-")
    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        extra={"request_id": request_id},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


try:
    from saq.web.starlette import saq_web

    app.mount("/monitor", saq_web("/monitor", queues=[orchestration_queue, checks_queue]))
except ImportError:
    pass

static_dir = Path(__file__).parent.parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
