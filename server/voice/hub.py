from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import WebSocket

log = structlog.get_logger(__name__)

_hub: VoiceNarrationHub | None = None


def get_voice_hub() -> VoiceNarrationHub:
    global _hub
    if _hub is None:
        _hub = VoiceNarrationHub()
    return _hub


class VoiceNarrationHub:
    """Fan-out Cursor /speak lines to connected browser clients."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        log.info("voice_ws_connected", clients=self.subscriber_count)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        log.info("voice_ws_disconnected", clients=self.subscriber_count)

    async def broadcast_narration(
        self,
        *,
        text: str,
        persona: str | None,
        priority: bool,
    ) -> None:
        payload = {
            "type": "narration",
            "text": text,
            "persona": persona,
            "priority": priority,
        }
        await self._broadcast(payload)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_text(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
