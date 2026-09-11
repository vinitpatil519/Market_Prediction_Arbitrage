"""Websocket fan-out.

Clients get the full screen state on connect and a fresh snapshot after every
scan. Frames are snapshots rather than deltas: the payload is a few hundred
kilobytes at most, and a client that reconnects mid-session is immediately
correct instead of having to replay a delta log.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.services.engine_runner import get_runner

router = APIRouter(tags=["stream"])


@router.websocket("/ws/stream")
async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    runner = get_runner()
    queue = runner.subscribe()

    try:
        await websocket.send_json(runner.snapshot())
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                # Keep intermediaries from reaping an idle socket during a
                # quiet market.
                await websocket.send_json({"type": "heartbeat"})
                continue
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        runner.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()
