from fastapi.testclient import TestClient

from meeting_copilot.app_state import AppState, ConnectionManager
from meeting_copilot.main import app


def test_websocket_connects_and_disconnects_cleanly(settings):
    with TestClient(app) as test_client:
        test_client.app.state.copilot = AppState(settings)
        with test_client.websocket_connect("/ws/events") as websocket:
            websocket.close()


class _FakeWebSocket:
    """Duck-types just enough of Starlette's WebSocket for ConnectionManager."""

    def __init__(self, fail_on_send: bool = False):
        self.accepted = False
        self.sent: list[str] = []
        self._fail_on_send = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, message: str) -> None:
        if self._fail_on_send:
            raise RuntimeError("connection closed")
        self.sent.append(message)


async def test_connection_manager_broadcasts_to_all_connected_clients():
    manager = ConnectionManager()
    ws_a = _FakeWebSocket()
    ws_b = _FakeWebSocket()
    await manager.connect(ws_a)
    await manager.connect(ws_b)

    await manager.broadcast("transcript.segment", {"text": "hello"})

    assert len(ws_a.sent) == 1
    assert len(ws_b.sent) == 1
    assert '"type": "transcript.segment"' in ws_a.sent[0]
    assert '"hello"' in ws_a.sent[0]


async def test_connection_manager_drops_dead_connections_on_broadcast():
    manager = ConnectionManager()
    healthy = _FakeWebSocket()
    dead = _FakeWebSocket(fail_on_send=True)
    await manager.connect(healthy)
    await manager.connect(dead)

    await manager.broadcast("session.status", {"whisper": "running"})
    # Second broadcast should not raise even though `dead` failed once and
    # should have been pruned from the connection set.
    await manager.broadcast("session.status", {"whisper": "running"})

    assert len(healthy.sent) == 2
