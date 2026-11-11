"""Shared SSE helpers.

Keepalives are handled by FastAPI itself: any route declaring
`response_class=EventSourceResponse` is wrapped by the routing layer's
keepalive inserter, which emits a `: ping` comment whenever the generator
has been idle for `fastapi.sse._PING_INTERVAL` (15s). Don't hand-roll a
per-route heartbeat timer on top of it -- that just adds a second, slower
ping alongside the framework's. If 15s ever proves too slow for a proxy or
load balancer in front of us, override that single interval centrally and
record the timeout being targeted.
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import HTTPException


def sse_capacity_guard(semaphore: asyncio.Semaphore):
    """Build a dependency that 503s when `semaphore` is exhausted.

    Must run as a Depends(), not as inline code in the SSE generator body --
    FastAPI sends the text/event-stream response headers (status 200) before
    the endpoint generator is first iterated, so an HTTPException raised
    inside the generator can no longer change the response status. Running
    this as a dependency-with-yield means it resolves (and can reject) before
    any part of the streaming response is sent, and holds the semaphore for
    the full duration of the connection since FastAPI doesn't tear down
    dependencies until after the streaming response completes.
    """

    async def _guard() -> AsyncIterator[None]:
        if semaphore.locked():
            raise HTTPException(status_code=503, detail="Too many concurrent SSE connections")
        async with semaphore:
            yield

    return _guard
