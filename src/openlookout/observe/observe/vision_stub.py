"""Optional cheap local-model vision adapter — contract only.

Used AFTER a CaptureHook returns a frame. Classifies stalemate/dialog type.
Does not own capture; does not run continuously.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class FrameVerdict:
    stuck: bool = False
    kind: str = "unknown"       # error_dialog | form_blocker | empty_page | unclear | ok
    confidence: float = 0.0
    summary: str = ""
    evidence: list = field(default_factory=list)


@runtime_checkable
class VisionAdapter(Protocol):
    def judge_frame(self, png_bytes: bytes, *, app: str = "", title: str = "", hint: str = "") -> FrameVerdict:
        ...


class NullVision:
    """No local model loaded — always unclear / not stuck."""
    def judge_frame(self, png_bytes: bytes, *, app: str = "", title: str = "", hint: str = "") -> FrameVerdict:
        return FrameVerdict(stuck=False, kind="unclear", confidence=0.0, summary="no vision adapter")


class KeywordHeuristicVision:
    """Test/dev stand-in: if hint or embedded text mentions error dialogs, mark stuck.

    Not a real model. Real adapter should wrap llama.cpp / onnx / etc. under same Protocol.
    """
    ERRORISH = ("error", "错误", "失败", "无法", "can't", "cannot", "err_", "dialog", "对话框")

    def judge_frame(self, png_bytes: bytes, *, app: str = "", title: str = "", hint: str = "") -> FrameVerdict:
        blob = f"{app} {title} {hint}".lower()
        hit = [w for w in self.ERRORISH if w in blob]
        if hit:
            return FrameVerdict(True, "error_dialog", 0.55, f"heuristic:{','.join(hit[:3])}", hit)
        return FrameVerdict(False, "unclear", 0.2, "heuristic:no_keyword")
