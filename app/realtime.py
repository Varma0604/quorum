from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    """Single-process room broadcaster. Persisted content remains canonical in PostgreSQL."""
    def __init__(self):
        self.rooms: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, document_id: int, websocket: WebSocket):
        await websocket.accept()
        self.rooms[document_id].add(websocket)

    def disconnect(self, document_id: int, websocket: WebSocket):
        self.rooms[document_id].discard(websocket)
        if not self.rooms[document_id]:
            self.rooms.pop(document_id, None)

    async def broadcast(self, document_id: int, message: dict, sender: WebSocket | None = None):
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


manager = ConnectionManager()
