"""E1: synthetic UI traces → FakeNovel (no network discover)."""
from __future__ import annotations
import json, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

def _resolve_root() -> Path:
    """Prefer sync/ or src/openlookout (has novel+investigate); not bare openlookout/sprite."""
    here = Path(__file__).resolve().parent
    cands = [
        here.parents[1] / "sync",                 # research/microexp → openlookout/sync
        here.parents[1],                          # sync/research/microexp → sync (=sprite root)
        here.parents[1] / "src" / "openlookout",
    ]
    for c in cands:
        if (c / "sprite" / "novel.py").is_file() and (c / "sprite" / "investigate.py").is_file():
            return c
    raise SystemExit("cannot find sprite.novel; use tree under sync or src/openlookout")

ROOT = _resolve_root()
sys.path.insert(0, str(ROOT))

from sprite.investigate import Candidate, Understanding, InvestigatorRegistry, Investigator, investigator_scenario
from sprite.novel import FakeNovelClient, NovelUnderstander
from sprite.framework import Engine, Registry


def main():
    now = 1_800_000_000.0
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        rows = [
            {"ts": datetime.fromtimestamp(now - 400, tz=timezone.utc).isoformat(),
             "type": "focus", "app": "WeirdCAD", "title": "参数面板 ???", "dur_s": 220},
            {"ts": datetime.fromtimestamp(now - 30, tz=timezone.utc).isoformat(),
             "type": "browser_error", "url": "https://example.invalid/x", "error": "ERR_EMPTY_RESPONSE"},
        ]
        (home / "events.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        client = FakeNovelClient(dict(
            what="陌生 CAD 久停 + 偶发浏览空响应", why="不定死为网络类，先可逆记下",
            state="unknown", confidence=0.8, act=True,
            candidate_actions=[dict(kind="archive_note", args={}, reason="记下", risk="safe", reversible="full")],
        ))
        novel = NovelUnderstander(home, clock=lambda: now, client=client, enabled=True, prefer_novel=True)
        ireg = InvestigatorRegistry()

        def disc(w):
            return [Candidate("anomaly", "a:ui1", "合成 UI 异常",
                              signals=dict(need=1.0, severity=0.45, unit="处"), ctx=dict(home=str(home)))]

        def gather(c, facts, world, view):
            lines = (home / "events.jsonl").read_text(encoding="utf-8").splitlines()
            facts["n_events"] = len(lines)
            return [f"events={len(lines)}", "合成 dwell+browser_error（非穷尽类）"]

        ireg.discoverer("anomaly", disc)
        ireg.gatherer("anomaly", lambda c: c.kind == "anomaly", gather)
        ireg.judge("anomaly", lambda c, f: Understanding(
            c.key, c.kind, c.title, state="unknown", confidence=0.15, act=False, why="本地不定性"))
        ireg.responder("anomaly", lambda c, u, w: [], lambda c, w: 1.0)

        class V:
            def now(self): return now
            def self_pid(self): return -1
            def procs(self): return {}
            def open_files(self, pid): return []
            def newest_mtime(self, *a, **k): return None
            def git_root(self, path): return None
            def git_dirty(self, root): return None
            def read_head(self, path, n=4000): return ""
            def exists(self, path): return Path(path).exists()

        inv = Investigator(ireg, V(), home, lambda: now, log=lambda *a: None, novel=novel, prefer_novel=True)
        sc = investigator_scenario(ireg, inv, live=True, min_conf=0.70, log=lambda *a: None, name="e1")
        eh = home / "eh"; eh.mkdir()
        reg = Registry(); reg.register(sc)
        outs = Engine(reg, eh, clock=lambda: now).step(None)
        acted = [a for o in outs for a in o.acted]
        result = dict(
            experiment="E1",
            novel_calls=len(client.calls),
            acted_kinds=[a.kind for a in acted],
            network_discoverer=("network_break" in ireg.discoverers),
            ok=bool(client.calls and acted and "network_break" not in ireg.discoverers),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
