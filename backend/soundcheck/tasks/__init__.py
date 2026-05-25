"""SAQ task functions split by queue responsibility."""

from typing import TypedDict

from redis.asyncio import Redis
from saq import Queue
from sqlalchemy.ext.asyncio import async_sessionmaker


class TaskContext(TypedDict, total=False):
    """Typed SAQ worker context populated by lifecycle startup hooks."""

    session_factory: async_sessionmaker
    redis: Redis
    orchestration_queue: Queue
    checks_queue: Queue
