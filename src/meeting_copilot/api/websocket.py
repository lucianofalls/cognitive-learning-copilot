"""WS /ws/events -- section 20.

The socket is purely a broadcast channel: the browser does not send
transcript data over it, only the server pushes events (transcript
segments, status changes, coach responses, direct-question detections).
Client-to-server messages are accepted but currently only used as a
keepalive/ping so the connection is not treated as idle by intermediaries.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from meeting_copilot.logging_config import log_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    state = websocket.app.state.copilot
    await state.connections.connect(websocket)
    log_event(logger, "websocket", "client_connected")
    try:
        while True:
            # We don't require the client to send anything, but reading
            # keeps the connection object accurate about disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await state.connections.disconnect(websocket)
        log_event(logger, "websocket", "client_disconnected")
