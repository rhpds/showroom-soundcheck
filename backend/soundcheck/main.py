"""FastAPI application entry point."""

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import API_KEY, CORS_ORIGINS, warn_default_credentials
from .database import async_session_factory
from .routes import check, groups, health, sessions
from .services import babylon_client, session_service
from .worker import checks_queue, orchestration_queue

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s",
    defaults={"request_id": "-"},
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    warn_default_credentials()
    babylon_client._default_manager.init_clients()
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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request ID (accept from client or generate) and return it in the response."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
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
