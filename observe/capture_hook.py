"""Triggered single-frame capture — backup eyes, NEVER an always-on loop.

Contract:
  CaptureHook.capture(req) → bytes | path | None
  Called only when a discoverer already has a stalemate / failure hypothesis.
  Implementations must not start background screenshot loops.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class TriggerRequest:
    reason: str                 # e.g. "stalemate_dwell", "browse_error"
    app: str = ""
    title: str = ""
    key: str = ""               # problem key for journaling
    max_side_px: int = 1024     # hint: downscale; cheap local model input
    # Optional ROI hint (left, top, right, bottom) in screen coords — Windows only when filled
    roi: tuple[int, int, int, int] | None = None


@runtime_checkable
class CaptureHook(Protocol):
    def capture(self, req: TriggerRequest):
        """Return PNG bytes, a filesystem path, or None if unavailable.

        MUST be synchronous one-shot. MUST NOT spawn a continuous capture loop.
        """
        ...


class NullCapture:
    """Default: no screen access. Tests and headless box use this."""
    def capture(self, req: TriggerRequest):
        return None


# --- Windows-oriented stub (not imported on Linux unless explicitly requested) ---
def windows_gdi_capture(req: TriggerRequest):  # pragma: no cover — needs win32
    """WIN32-ONLY: BitBlt one frame of the foreground window (or ROI).

    Marked for PC return. Not wired into any loop. Import guarded by sys.platform.
    """
    import sys
    if sys.platform != "win32":
        raise RuntimeError("windows_gdi_capture is Windows-only")
    # Intentionally unimplemented body on box; PC agent fills BitBlt + PNG encode.
    raise NotImplementedError("BitBlt one-shot pending PC return — interface only")
