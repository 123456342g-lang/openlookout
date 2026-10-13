"""僵局传感器 / 轻执行插件（不是「软件卡住专用主脑」）。

只通过 investigate.InvestigatorRegistry 注册。立案信号（操作日志为主，不靠常驻截图）：
  - focus dwell / flicker / 错误标题弱信号
  - 可选：触发式单帧 CaptureHook + VisionAdapter（绝非常驻截图循环）
问题「是什么」默认交给 novel；本插件只开 generic 问题 + 白名单记下僵局。
默认不代点 UI。live+apply_real 才产生 Action。
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from ..framework import Action
from ..investigate import (
    Candidate, Understanding, InvestigatorRegistry, Investigator,
    investigator_scenario,
)

# Optional observe imports — keep sprite importable even if observe not on path
try:
    from observe.eventlog import EventLog, dwell_signals, flicker_signals
    from observe.capture_hook import CaptureHook, NullCapture, TriggerRequest
    from observe.vision_stub import VisionAdapter, NullVision
except ImportError:  # pragma: no cover
    EventLog = None  # type: ignore
    dwell_signals = flicker_signals = None  # type: ignore
    CaptureHook = NullCapture = TriggerRequest = None  # type: ignore
    VisionAdapter = NullVision = None  # type: ignore

ERROR_TITLE_RE = re.compile(
    r"(?i)error|错误|失败|无法|exception|crash|崩溃|not responding|未响应|"
    r"对话框|dialog|warning|警告"
)
SELF_APP_RE = re.compile(r"(?i)openlookout|sprite|pythonw?$")


class StalemateKit:
    def __init__(
        self,
        home: Path,
        clock=time.time,
        *,
        event_paths: list | None = None,
        min_dwell_s: float = 180.0,
        flicker_window_s: float = 180.0,
        flicker_min_switches: int = 8,
        capture: "CaptureHook | None" = None,
        vision: "VisionAdapter | None" = None,
        trigger_capture: bool = True,
    ):
        self.home = Path(home)
        self.clock = clock
        self.event_paths = [Path(p) for p in (event_paths or [])]
        self.min_dwell_s = min_dwell_s
        self.flicker_window_s = flicker_window_s
        self.flicker_min_switches = flicker_min_switches
        self.capture = capture if capture is not None else (NullCapture() if NullCapture else None)
        self.vision = vision if vision is not None else (NullVision() if NullVision else None)
        self.trigger_capture = trigger_capture
        self._shot_dir = self.home / "stalemate_shots"
        self.state: dict = {}

    def _log(self) -> "EventLog":
        if EventLog is None:
            raise RuntimeError("observe.eventlog not importable")
        if self.event_paths:
            return EventLog(self.event_paths)
        return EventLog.from_home(self.home)

    def discover(self, world=None) -> list:
        if dwell_signals is None:
            return []
        now = float(self.clock())
        ev = self._log().events(types={"focus"}, since=now - 1200.0)
        out: list[Candidate] = []
        for d in dwell_signals(ev, now=now, min_dwell_s=self.min_dwell_s, window_s=900.0):
            app, title = d["app"], d["title"]
            if SELF_APP_RE.search(app or ""):
                continue
            if not app and not title:
                continue
            key = f"stalemate:dwell:{app}:{hash(title) & 0xFFFFFFFF:x}"
            errish = bool(ERROR_TITLE_RE.search(title or ""))
            need = 1.0 + (0.5 if errish else 0.0) + min(d["dwell_s"] / 600.0, 1.0)
            out.append(Candidate(
                "stalemate", key, f"可能卡在：{app or '?'}｜{(title or '')[:60]}",
                signals=dict(need=need, severity=0.35 if not errish else 0.55, unit="僵局",
                             kind_signal="dwell", dwell_s=d["dwell_s"], hits=d["hits"]),
                ctx=dict(app=app, title=title, signal="dwell", dwell_s=d["dwell_s"], errish=errish),
            ))
        for f in flicker_signals(
            ev, now=now, window_s=self.flicker_window_s,
            min_switches=self.flicker_min_switches, pair_min=max(4, self.flicker_min_switches // 2),
        ):
            key = f"stalemate:flicker:{hash((f['a_app'], f['a_title'], f['b_app'], f['b_title'])) & 0xFFFFFFFF:x}"
            out.append(Candidate(
                "stalemate", key,
                f"窗口来回切：{f['a_app'] or '?'} ↔ {f['b_app'] or '?'}",
                signals=dict(need=1.2, severity=0.4, unit="僵局", kind_signal="flicker", switches=f["switches"]),
                ctx=dict(signal="flicker", **{k: f[k] for k in f}),
            ))
        return out

    def gather(self, cand, facts, world, view):
        lines = []
        ctx = cand.ctx
        facts["signal"] = ctx.get("signal")
        facts["app"] = ctx.get("app") or ctx.get("a_app") or ""
        facts["title"] = ctx.get("title") or ctx.get("a_title") or ""
        if ctx.get("signal") == "dwell":
            facts["dwell_s"] = ctx.get("dwell_s")
            lines.append(f"同一窗口停留约 {ctx.get('dwell_s', 0):.0f}s（focus 累加）")
            if ctx.get("errish"):
                facts["errorish_title"] = True
                lines.append("标题含错误/对话框暗示")
        elif ctx.get("signal") == "flicker":
            facts["switches"] = ctx.get("switches")
            lines.append(f"约 {ctx.get('switches')} 次窗口间快速切换")
            lines.append(f"A={ctx.get('a_app')}|{str(ctx.get('a_title') or '')[:40]}")
            lines.append(f"B={ctx.get('b_app')}|{str(ctx.get('b_title') or '')[:40]}")

        # Triggered backup eyes — one shot only when hypothesis already exists
        if self.trigger_capture and self.capture and TriggerRequest and ctx.get("signal") == "dwell":
            req = TriggerRequest(
                reason="stalemate_dwell",
                app=str(facts.get("app") or ""),
                title=str(facts.get("title") or ""),
                key=cand.key,
            )
            try:
                frame = self.capture.capture(req)
            except Exception as e:
                lines.append(f"[触发截图失败：{type(e).__name__}]")
                frame = None
            if frame:
                facts["frame_captured"] = True
                path = self._save_frame(cand.key, frame)
                if path:
                    facts["frame_path"] = str(path)
                    lines.append(f"已存触发截图：{path.name}")
                if self.vision:
                    raw = frame if isinstance(frame, (bytes, bytearray)) else None
                    if raw is None and path:
                        try:
                            raw = Path(path).read_bytes()
                        except OSError:
                            raw = None
                    if raw:
                        v = self.vision.judge_frame(
                            raw, app=facts.get("app") or "", title=facts.get("title") or "",
                            hint=facts.get("title") or "",
                        )
                        facts["vision_kind"] = v.kind
                        facts["vision_stuck"] = v.stuck
                        facts["vision_confidence"] = v.confidence
                        lines.append(f"视觉后备：{v.kind} stuck={v.stuck} conf={v.confidence:.2f} {v.summary}")
            else:
                lines.append("无触发截图（NullCapture/不可用）— 仅靠操作日志")
        else:
            lines.append("未触发截图（日志信号已足够立案或未启用）")
        return lines

    def _save_frame(self, key: str, frame):
        self._shot_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w.-]+", "_", key)[:80] + ".png"
        path = self._shot_dir / name
        try:
            if isinstance(frame, (bytes, bytearray)):
                path.write_bytes(frame)
            else:
                # path-like from hook
                src = Path(frame)
                path.write_bytes(src.read_bytes())
            return path
        except Exception:
            return None


def judge_stalemate(cand: Candidate, facts: dict) -> Understanding:
    """本地只标白名单线索；定性留给 novel。无 novel 时回退为可逆记下。"""
    u = Understanding(cand.key, cand.kind, cand.title)
    u.what = f"信号={facts.get('signal')} 应用={facts.get('app') or '?'}"
    u.state = "unknown"
    dwell = facts.get("dwell_s") or 0
    switches = facts.get("switches") or 0
    vision_stuck = bool(facts.get("vision_stuck"))
    vision_conf = float(facts.get("vision_confidence") or 0)
    facts["whitelist_hints"] = dict(dwell_s=dwell, switches=switches,
                                    vision_stuck=vision_stuck, errish=bool(facts.get("errorish_title")))

    if facts.get("signal") == "dwell" and dwell >= 300:
        u.act, u.confidence = True, 0.78
        u.why = f"传感器：同窗停留 {dwell:.0f}s（白名单可记下）"
    elif facts.get("signal") == "dwell" and dwell >= 180:
        u.act, u.confidence = True, 0.76
        u.why = f"传感器：同窗停留 {dwell:.0f}s"
    elif facts.get("signal") == "flicker" and switches >= 8:
        u.act, u.confidence = True, 0.76
        u.why = f"传感器：窗口来回切 {switches} 次"
    else:
        u.confidence = 0.3
        u.why = "僵局传感器证据不足"
        return u

    if vision_stuck and vision_conf >= 0.5:
        u.confidence = min(0.85, u.confidence + 0.08)
        u.why += f"；视觉后备={facts.get('vision_kind')}"
    if facts.get("errorish_title"):
        u.confidence = min(0.85, u.confidence + 0.05)
        u.why += "；标题像错误框"
    return u


def propose_stalemate(cand, u, world):
    """Reversible light touch: archive understanding note. Does not click UI."""
    home = Path(getattr(world, "home", None) or cand.ctx.get("home") or ".")
    notes = home / "stalemate_notes"
    notes.mkdir(parents=True, exist_ok=True)
    note = notes / (re.sub(r"[^\w.-]+", "_", cand.key)[:80] + ".json")
    payload = dict(key=cand.key, title=cand.title, why=u.why, facts={k: v for k, v in (u.facts or {}).items()
                   if isinstance(v, (str, int, float, bool, list, type(None)))}, ts=time.time())

    def dry():
        return True

    def run():
        note.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return dict(note=str(note))

    def verify(r):
        return Path((r or {}).get("note") or note).is_file()

    def undo(r):
        try:
            Path((r or {}).get("note") or note).unlink(missing_ok=True)
        except OSError:
            pass

    return [Action(
        "stalemate_note",
        f"记下僵局：{(cand.title or '')[:40]}",
        "safe",
        "full",
        relief=0.5,
        reason=u.why,
        confident=True,
        value_s=120.0,
        dry_run=dry,
        run=run,
        verify=verify,
        undo=undo,
        done_text=lambda xs: f"已记下僵局并准备协助：{(cand.title or '')[:40]}",
        done_short=lambda xs: "已记下僵局",
    )]


def recheck_stalemate(cand, world):
    """Still open while dwell/flicker signal persists for same key."""
    kit = cand.ctx.get("_kit")
    if not kit:
        return 0.0
    try:
        still = [c for c in kit.discover(world) if c.key == cand.key]
    except Exception:
        return 0.0
    if not still:
        return 0.0
    return float(still[0].signals.get("need", 1.0))


def register_all(ireg: InvestigatorRegistry, kit: StalemateKit):
    ireg.discoverer("stalemate", kit.discover)

    def applies(c: Candidate):
        return c.kind == "stalemate"

    def gather(c, facts, world, view):
        c.ctx["_kit"] = kit
        return kit.gather(c, facts, world, view)

    ireg.gatherer("stalemate", applies, gather)
    ireg.judge("stalemate", judge_stalemate)

    def propose(c, u, w):
        c.ctx.setdefault("home", str(kit.home))
        return propose_stalemate(c, u, w)

    def rc(c, w):
        c.ctx["_kit"] = kit
        return recheck_stalemate(c, w)

    ireg.responder("stalemate", propose, rc)
    return ireg


def build(home: Path, live=False, apply_real=False, log=print, novel=None, novel_from_env=False, **kit_kw):
    home = Path(home)
    kit = StalemateKit(home, **kit_kw)
    ireg = InvestigatorRegistry()
    register_all(ireg, kit)
    if novel is None and novel_from_env:
        from ..novel import NovelUnderstander
        novel = NovelUnderstander.from_env(home, clock=kit.clock, log=log)
    inv = Investigator(ireg, view=None, home=home, clock=kit.clock, log=log, novel=novel)
    # view unused by stalemate gatherers that only read eventlog; Investigator still calls gatherers
    class _NullView:
        def now(self): return kit.clock()
        def self_pid(self): return -1
        def procs(self): return {}
        def open_files(self, pid): return []
        def newest_mtime(self, *a, **k): return None
        def git_root(self, path): return None
        def git_dirty(self, root): return None
        def read_head(self, path, n=4000): return ""
        def exists(self, path): return Path(path).exists()
    inv.view = _NullView()
    sc = investigator_scenario(ireg, inv, live=live and apply_real, min_conf=0.70, log=log, name="stalemate")
    return sc, kit
