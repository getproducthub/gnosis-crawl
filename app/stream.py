"""Live browser stream: CDP screencast → WebSocket / MJPEG relay.

Uses Chrome DevTools Protocol (CDP) Page.startScreencast to capture
JPEG frames from a Playwright page, then relays them to clients via:

  - WebSocket  `/stream/{session_id}`        — base64 JPEG frames as text messages
  - MJPEG      `/stream/{session_id}/mjpeg`   — multipart/x-mixed-replace stream

The stream is fed from a PoolSlot (see browser_pool.py). Each session
gets its own dedicated browser tab.

Architecture:
  Client connects → acquire pool slot → navigate to URL →
  start CDP screencast → relay frames → client disconnects →
  stop screencast → release slot
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.browser_pool import get_browser_pool, PoolSlot

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


# ---------------------------------------------------------------------------
# CDP Screencast wrapper
# ---------------------------------------------------------------------------

@dataclass
class ScreencastSession:
    """Manages CDP screencast on a Playwright page."""
    slot: PoolSlot
    quality: int = 25
    max_width: int = 854
    max_height: int = 480
    _running: bool = False
    _frame_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=5))
    _cdp: Optional[object] = None
    _frame_count: int = 0

    async def start(self) -> None:
        """Begin CDP screencast and route frames to the internal queue."""
        if self._running:
            return

        page = self.slot.page
        if not page or page.is_closed():
            raise RuntimeError("Page is closed or missing")

        # Get CDP session from Playwright page
        self._cdp = await page.context.new_cdp_session(page)

        # Listen for screencast frames
        self._cdp.on("Page.screencastFrame", self._on_frame)

        await self._cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": self.quality,
            "maxWidth": self.max_width,
            "maxHeight": self.max_height,
            "everyNthFrame": 1,
        })

        self._running = True
        logger.info(
            "Screencast started for session %s (quality=%d, %dx%d)",
            self.slot.session_id, self.quality, self.max_width, self.max_height,
        )

    async def stop(self) -> None:
        """Stop the CDP screencast."""
        if not self._running:
            return

        self._running = False

        try:
            if self._cdp:
                await self._cdp.send("Page.stopScreencast")
                await self._cdp.detach()
        except Exception as exc:
            logger.warning("Error stopping screencast: %s", exc)

        self._cdp = None
        logger.info(
            "Screencast stopped for session %s (%d frames captured)",
            self.slot.session_id, self._frame_count,
        )

    def _on_frame(self, params: dict) -> None:
        """CDP callback: receive a screencast frame."""
        if not self._running:
            return

        self._frame_count += 1

        # Acknowledge frame to CDP (required to keep receiving)
        session_id = params.get("sessionId", 0)
        if self._cdp:
            asyncio.ensure_future(
                self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
            )

        # Push frame data (base64-encoded JPEG) to queue, drop if full
        frame_data = params.get("data", "")
        if frame_data:
            try:
                self._frame_queue.put_nowait(frame_data)
            except asyncio.QueueFull:
                # Drop oldest frame to keep stream fresh
                try:
                    self._frame_queue.get_nowait()
                    self._frame_queue.put_nowait(frame_data)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def get_frame(self, timeout: float = 2.0) -> Optional[str]:
        """Get the next base64-encoded JPEG frame. Returns None on timeout."""
        try:
            return await asyncio.wait_for(self._frame_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None


# ---------------------------------------------------------------------------
# Active stream sessions
# ---------------------------------------------------------------------------

_active_streams: dict[str, ScreencastSession] = {}


async def _start_stream(session_id: str, url: str) -> ScreencastSession:
    """Acquire a pool slot, navigate, and start screencast."""
    pool = await get_browser_pool()
    slot = await pool.acquire(session_id)

    if slot is None:
        raise HTTPException(
            status_code=503,
            detail="No browser slots available. Try again later.",
        )

    try:
        # Navigate to the requested URL
        await slot.page.goto(url, timeout=settings.browser_timeout, wait_until="domcontentloaded")
        slot.navigated_url = url

        # Start screencast
        sc = ScreencastSession(
            slot=slot,
            quality=settings.browser_stream_quality,
            max_width=settings.browser_stream_max_width,
            max_height=int(settings.browser_stream_max_width * 9 / 16),
        )
        await sc.start()

        _active_streams[session_id] = sc
        return sc

    except Exception:
        await pool.release(slot)
        raise


async def _stop_stream(session_id: str) -> None:
    """Stop screencast and release the pool slot."""
    sc = _active_streams.pop(session_id, None)
    if sc is None:
        return

    await sc.stop()

    pool = await get_browser_pool()
    await pool.release(sc.slot)
    logger.info("Stream session %s cleaned up", session_id)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/stream/{session_id}")
async def websocket_stream(
    websocket: WebSocket,
    session_id: str,
    url: str = Query(..., description="URL to stream"),
):
    """Live browser viewport stream over WebSocket.

    Connect with: ws://host/stream/{session_id}?url=https://example.com

    Receives base64-encoded JPEG frames as text messages.
    Send JSON commands to interact:
      {"action": "navigate", "url": "https://..."}
      {"action": "click", "selector": "#btn"}
      {"action": "scroll", "direction": "down"}
      {"action": "stop"}
    """
    await websocket.accept()
    logger.info("WebSocket stream connected: session=%s, url=%s", session_id, url)

    sc: Optional[ScreencastSession] = None

    try:
        sc = await _start_stream(session_id, url)

        # Send initial metadata
        await websocket.send_json({
            "type": "meta",
            "session_id": session_id,
            "url": url,
            "width": sc.max_width,
            "height": sc.max_height,
            "quality": sc.quality,
        })

        # Two concurrent tasks: relay frames out + receive commands in
        async def relay_frames():
            while True:
                frame = await sc.get_frame(timeout=2.0)
                if frame:
                    await websocket.send_json({
                        "type": "frame",
                        "data": frame,
                        "seq": sc._frame_count,
                    })
                else:
                    # Send keepalive
                    await websocket.send_json({"type": "ping"})

        async def receive_commands():
            while True:
                data = await websocket.receive_json()
                action = data.get("action", "")

                if action == "navigate" and data.get("url"):
                    new_url = data["url"]
                    logger.info("Stream navigate: %s → %s", session_id, new_url)
                    await sc.slot.page.goto(new_url, timeout=30000, wait_until="domcontentloaded")
                    sc.slot.navigated_url = new_url
                    await websocket.send_json({"type": "navigated", "url": new_url})

                elif action == "click" and data.get("selector"):
                    await sc.slot.page.click(data["selector"], timeout=5000)
                    await websocket.send_json({"type": "clicked", "selector": data["selector"]})

                elif action == "scroll":
                    direction = data.get("direction", "down")
                    delta = 300 if direction == "down" else -300
                    await sc.slot.page.mouse.wheel(0, delta)
                    await websocket.send_json({"type": "scrolled", "direction": direction})

                elif action == "type" and data.get("selector") and data.get("text"):
                    await sc.slot.page.fill(data["selector"], data["text"])
                    await websocket.send_json({"type": "typed", "selector": data["selector"]})

                elif action == "stop":
                    await websocket.send_json({"type": "stopped"})
                    return

                else:
                    await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})

        # Run both concurrently, cancel the other when one finishes
        frame_task = asyncio.create_task(relay_frames())
        cmd_task = asyncio.create_task(receive_commands())

        done, pending = await asyncio.wait(
            [frame_task, cmd_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        logger.info("WebSocket stream disconnected: session=%s", session_id)
    except Exception as exc:
        logger.error("WebSocket stream error: %s", exc, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        await _stop_stream(session_id)


# ---------------------------------------------------------------------------
# MJPEG fallback endpoint
# ---------------------------------------------------------------------------

@router.get("/stream/{session_id}/mjpeg")
async def mjpeg_stream(
    session_id: str,
    url: str = Query(..., description="URL to stream"),
):
    """MJPEG live browser viewport stream (fallback for non-WebSocket clients).

    Returns a multipart/x-mixed-replace stream of JPEG frames.
    Viewable directly in <img> tags or any browser.
    """
    logger.info("MJPEG stream requested: session=%s, url=%s", session_id, url)

    sc = await _start_stream(session_id, url)

    async def frame_generator():
        try:
            while True:
                frame_b64 = await sc.get_frame(timeout=2.0)
                if frame_b64:
                    frame_bytes = base64.b64decode(frame_b64)
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n"
                        b"\r\n" + frame_bytes + b"\r\n"
                    )
                else:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await _stop_stream(session_id)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Stream-Session": session_id,
        },
    )


# ---------------------------------------------------------------------------
# Stream status / control
# ---------------------------------------------------------------------------

@router.get("/stream/{session_id}/status")
async def stream_status(session_id: str):
    """Check the status of an active stream session."""
    sc = _active_streams.get(session_id)
    if sc is None:
        return {"session_id": session_id, "active": False}

    return {
        "session_id": session_id,
        "active": True,
        "url": sc.slot.navigated_url,
        "frames_captured": sc._frame_count,
        "quality": sc.quality,
        "resolution": f"{sc.max_width}x{sc.max_height}",
        "slot_id": sc.slot.slot_id,
    }


@router.get("/stream/pool/status")
async def pool_status():
    """Get browser pool status."""
    if not settings.browser_stream_enabled:
        return {"enabled": False, "message": "Live streaming is disabled. Set BROWSER_STREAM_ENABLED=true."}

    pool = await get_browser_pool()
    return {"enabled": True, **pool.status()}
