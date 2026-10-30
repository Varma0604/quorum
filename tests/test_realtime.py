import asyncio
import json

from app.realtime import ConnectionManager


class FakeSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, body):
        self.published.append((channel, body))


def test_local_broadcast_skips_the_sender():
    async def check():
        manager = ConnectionManager(redis_url=None, instance_id="api-a")
        sender, peer = FakeSocket(), FakeSocket()
        manager.rooms[7].update({sender, peer})
        event = {"type": "document.updated", "version": 2}
        await manager.broadcast_local(7, event, sender=sender)
        assert sender.messages == []
        assert peer.messages == [event]

    asyncio.run(check())


def test_remote_event_envelope_identifies_its_origin_and_document():
    async def check():
        manager = ConnectionManager(redis_url=None, instance_id="api-a")
        fake_redis = FakeRedis()
        manager._redis = fake_redis
        event = {"type": "document.updated", "version": 2}
        await manager.publish_remote(7, event)
        assert fake_redis.published[0][0] == "quorum:documents:7"
        assert json.loads(fake_redis.published[0][1]) == {
            "origin": "api-a", "document_id": 7, "event": event,
        }

    asyncio.run(check())
