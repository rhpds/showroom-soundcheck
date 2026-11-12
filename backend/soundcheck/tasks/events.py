"""Redis Pub/Sub event helpers shared by orchestration and check tasks."""

import json

# Key for the "metadata sync in progress" flag -- a short-lived Redis string,
# not a DB column, since it only matters to an open SSE stream and self-heals
# via TTL if a worker is killed mid-sync. Set by the route before enqueueing
# sync_metadata, cleared by the task in a finally block.
_METADATA_SYNC_TTL_SECONDS = 120


def _metadata_sync_key(group_id: str) -> str:
    return f"group:{group_id}:metadata_syncing"


async def publish_session_event(redis, session_id: str, event_type: str, data: dict) -> None:
    """Publish a progress event to the Redis Pub/Sub channel for this session."""
    payload = json.dumps({"type": event_type, "session_id": session_id, **data})
    await redis.publish(f"session:{session_id}", payload)


async def publish_group_event(redis, group_id: str | None, event_type: str) -> None:
    """Publish a notification to the group's Redis Pub/Sub channel."""
    if not group_id:
        return
    payload = json.dumps({"type": event_type, "group_id": group_id})
    await redis.publish(f"group:{group_id}", payload)


async def mark_metadata_syncing(redis, group_id: str) -> None:
    """Flag a group as mid metadata-sync and notify any open SSE stream.

    Called by the route before enqueueing sync_metadata so a stream opened
    (or already open) right after the POST sees active state immediately,
    instead of the SSE route's initial fetch seeing stale, non-running status
    and closing the connection before the worker ever publishes anything.
    """
    await redis.set(_metadata_sync_key(group_id), "1", ex=_METADATA_SYNC_TTL_SECONDS)
    await publish_group_event(redis, group_id, "metadata_sync_started")


async def clear_metadata_syncing(redis, group_id: str) -> None:
    """Clear the metadata-sync flag and notify so the stream delivers refreshed metadata."""
    await redis.delete(_metadata_sync_key(group_id))
    await publish_group_event(redis, group_id, "metadata_sync_complete")


async def is_metadata_syncing(redis, group_id: str) -> bool:
    return bool(await redis.exists(_metadata_sync_key(group_id)))
