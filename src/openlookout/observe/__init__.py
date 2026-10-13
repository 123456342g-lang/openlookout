"""Observation layer: operation-log events first; triggered single-frame capture only as backup eyes.

Public surface:
  events          — schema helpers for nav / url / browser_error / focus
  eventlog        — read/tail events.jsonl; dwell & flicker signals
  browser_ingest  — turn browser-extension POSTs into typed events (platform-agnostic)
  capture_hook    — optional one-shot frame capture interface (NOT a loop)
  vision_stub     — optional local-model vision adapter contract
"""
from .events import EVENT_TYPES, normalize_browser_payload, is_browser_error_code
from .eventlog import EventLog, dwell_signals, flicker_signals, browse_failures
from .browser_ingest import ingest_extension_payload, ExtensionIngestState
from .capture_hook import CaptureHook, NullCapture, TriggerRequest
from .vision_stub import VisionAdapter, NullVision, FrameVerdict

__all__ = [
    "EVENT_TYPES", "normalize_browser_payload", "is_browser_error_code",
    "EventLog", "dwell_signals", "flicker_signals", "browse_failures",
    "ingest_extension_payload", "ExtensionIngestState",
    "CaptureHook", "NullCapture", "TriggerRequest",
    "VisionAdapter", "NullVision", "FrameVerdict",
]
