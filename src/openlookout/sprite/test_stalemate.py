"""stalemate discoverer — fake events.jsonl, no Windows."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from sprite.framework import Engine, Registry
from sprite.investigate import InvestigatorRegistry, Investigator, investigator_scenario
from sprite.scenarios import stalemate as S
from observe.capture_hook import CaptureHook, TriggerRequest
from observe.vision_stub import KeywordHeuristicVision


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t
    def __call__(self):
        return self.t


class FakeCapture:
    def __init__(self):
        self.calls = []
    def capture(self, req: TriggerRequest):
        self.calls.append(req)
        return b"\x89PNG\r\n\x1a\nfake"


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def write_events(path: Path, clock: Clock):
    now = clock()
    rows = [
        {"ts": iso(now - 400), "type": "focus", "app": "excel", "title": "预算.xlsx", "dur_s": 320},
    ]
    # flicker burst
    for i in range(12):
        app, title = (("notepad", "草稿"), ("explorer", "文档"))[i % 2]
        rows.append({"ts": iso(now - 100 + i * 4), "type": "focus", "app": app, "title": title, "dur_s": 3})
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in rows) + "\n", encoding="utf-8")


def test_discover_dwell_and_flicker(tmp_path):
    clock = Clock()
    evp = tmp_path / "events.jsonl"
    write_events(evp, clock)
    kit = S.StalemateKit(tmp_path, clock, event_paths=[evp], min_dwell_s=180, flicker_min_switches=8, trigger_capture=False)
    cands = kit.discover()
    kinds = {c.ctx.get("signal") for c in cands}
    assert "dwell" in kinds
    assert "flicker" in kinds
    assert all(c.kind == "stalemate" for c in cands)


def test_triggered_capture_once(tmp_path):
    clock = Clock()
    evp = tmp_path / "events.jsonl"
    write_events(evp, clock)
    cap = FakeCapture()
    kit = S.StalemateKit(
        tmp_path, clock, event_paths=[evp], min_dwell_s=180,
        capture=cap, vision=KeywordHeuristicVision(), trigger_capture=True,
    )
    cands = [c for c in kit.discover() if c.ctx.get("signal") == "dwell"]
    assert cands
    facts = {}
    lines = kit.gather(cands[0], facts, None, None)
    assert cap.calls and cap.calls[0].reason == "stalemate_dwell"
    assert facts.get("frame_captured") is True
    assert any("触发截图" in x or "视觉后备" in x for x in lines)


def test_engine_acts_on_stalemate_live(tmp_path):
    clock = Clock()
    home = tmp_path / "home"
    home.mkdir()
    evp = home / "events.jsonl"
    write_events(evp, clock)
    sc, kit = S.build(home, live=True, apply_real=True, log=lambda *a: None, event_paths=[evp], min_dwell_s=180, trigger_capture=False)
    reg = Registry(); reg.register(sc)
    (home / "eh").mkdir(parents=True, exist_ok=True)
    eng = Engine(reg, home / "eh", clock=clock)
    class W: pass
    w = W(); w.home = home
    outs = eng.step(w)
    msgs = [o.text_done for o in outs if getattr(o, 'text_done', None)]
    acted = [a for o in outs for a in o.acted]
    # Should have acted (note written) for dwell
    notes = list((home / "stalemate_notes").glob("*.json")) if (home / "stalemate_notes").exists() else []
    assert acted or notes, (msgs, notes, [(o.skipped, o.acted) for o in outs])
    # understandings written
    assert (home / "understandings.jsonl").exists()


def test_no_user_host_hardcoded():
    src = Path(S.__file__).read_text(encoding="utf-8")
    assert "172.16.170.169" not in src
