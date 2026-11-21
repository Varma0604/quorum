import asyncio
import json

from app.realtime import ConnectionManager


class FakeSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)

    async def accept(self):
        return None


class FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, body):
        self.published.append((channel, body))


def test_local_broadcast_skips_the_sender():
    async def check():
        manager = ConnectionManager(redis_url=None, instance_id="api-a")
        sender, peer = FakeSocket(), FakeSocket()
        manager.rooms["document:7"].update({sender, peer})
        event = {"type": "document.updated", "version": 2}
        await manager.broadcast_local("document:7", event, sender=sender)
        assert sender.messages == []
        assert peer.messages == [event]

    asyncio.run(check())


def test_remote_event_envelope_identifies_its_origin_and_document():
    async def check():
        manager = ConnectionManager(redis_url=None, instance_id="api-a")
        fake_redis = FakeRedis()
        manager._redis = fake_redis
        event = {"type": "document.updated", "version": 2}
        await manager.publish_remote("document:7", event)
        assert fake_redis.published[0][0] == "quorum:rooms:document:7"
        assert json.loads(fake_redis.published[0][1]) == {
            "origin": "api-a", "room": "document:7", "event": event,
        }

    asyncio.run(check())


def test_incident_event_reaches_a_different_api_instance_and_reconnects():
    async def check():
        source = ConnectionManager(redis_url=None, instance_id="api-a")
        destination = ConnectionManager(redis_url=None, instance_id="api-b")
        source_redis = FakeRedis()
        source._redis = source_redis
        event = {"type": "incident.event", "incident_id": 19, "message": "Rollback started."}

        await source.publish_remote("incident:19", event)
        envelope = json.loads(source_redis.published[0][1])

        disconnected, reconnected = FakeSocket(), FakeSocket()
        await destination.connect("incident:19", disconnected)
        destination.disconnect("incident:19", disconnected)
        await destination.connect("incident:19", reconnected)
        await destination.deliver_remote(envelope)

        assert disconnected.messages == []
        assert reconnected.messages == [event]
        await source.deliver_remote(envelope)
        assert source.rooms.get("incident:19") is None

    asyncio.run(check())
