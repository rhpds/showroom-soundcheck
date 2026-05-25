"""Redis Pub/Sub event helpers shared by orchestration and check tasks."""

import json


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
