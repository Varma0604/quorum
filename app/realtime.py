import asyncio
import json
import os
import socket
from collections import defaultdict
from contextlib import suppress

from fastapi import WebSocket
from redis import asyncio as redis

from app.config import REDIS_URL


class ConnectionManager:
    """Local WebSocket rooms with optional Redis Pub/Sub between API instances."""
    def __init__(self, redis_url: str | None = REDIS_URL, instance_id: str | None = None):
        self.rooms: dict[int, set[WebSocket]] = defaultdict(set)
        self.redis_url = redis_url
        self.instance_id = instance_id or os.getenv("INSTANCE_ID", f"{socket.gethostname()}-{os.getpid()}")
        self._redis: redis.Redis | None = None
        self._listener: asyncio.Task | None = None

    @staticmethod
    def channel(document_id: int) -> str:
        return f"quorum:documents:{document_id}"

    async def start(self):
        """Start one Redis pattern subscriber for this API instance, if configured."""
        if not self.redis_url:
            return
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        self._listener = asyncio.create_task(self._listen(), name="quorum-redis-pubsub")

    async def stop(self):
        if self._listener:
            self._listener.cancel()
            with suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    async def _listen(self):
        assert self._redis is not None
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.psubscribe("quorum:documents:*")
        try:
            async for item in pubsub.listen():
                if item.get("type") != "pmessage":
                    continue
                envelope = json.loads(item["data"])
                if envelope.get("origin") == self.instance_id:
                    continue
                document_id = int(envelope["document_id"])
                await self.broadcast_local(document_id, envelope["event"])
        finally:
            await pubsub.aclose()

    async def connect(self, document_id: int, websocket: WebSocket):
        await websocket.accept()
        self.rooms[document_id].add(websocket)

    def disconnect(self, document_id: int, websocket: WebSocket):
        self.rooms[document_id].discard(websocket)
        if not self.rooms[document_id]:
            self.rooms.pop(document_id, None)

    async def broadcast_local(self, document_id: int, message: dict, sender: WebSocket | None = None):
        dead = []
        for connection in tuple(self.rooms.get(document_id, ())):
            if connection is sender:
                continue
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(document_id, connection)

    async def publish_remote(self, document_id: int, event: dict):
        """Publish after the database transaction commits; no-op for local-only development."""
        if self._redis is None:
            return
        envelope = {"origin": self.instance_id, "document_id": document_id, "event": event}
        await self._redis.publish(self.channel(document_id), json.dumps(envelope))


manager = ConnectionManager()
