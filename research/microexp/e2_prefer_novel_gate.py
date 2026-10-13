"""E2: prefer_novel True vs False when local already confident."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

def _resolve_root() -> Path:
    here = Path(__file__).resolve().parent
    cands = [
        here.parents[1] / "sync",                 # research/microexp → openlookout/sync
        here.parents[1],                          # sync/research/microexp → sync (=sprite root)
        here.parents[1] / "src" / "openlookout",
    ]
    for c in cands:
        if (c / "sprite" / "novel.py").is_file() and (c / "sprite" / "investigate.py").is_file():
            return c
    raise SystemExit("cannot find sprite.novel")

ROOT = _resolve_root()
sys.path.insert(0, str(ROOT))

from sprite.investigate import Candidate, Understanding
from sprite.novel import FakeNovelClient, NovelUnderstander, needs_novel


def main():
    prior = Understanding("k", "anomaly", "t", state="in_use", confidence=0.9, act=True, why="本地白名单自信")
    c = Candidate("anomaly", "k", "t")
    assert needs_novel(prior, prefer_novel=True) is True
    assert needs_novel(prior, prefer_novel=False) is False

    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        clock = lambda: 1_800_000_000.0
        c1 = FakeNovelClient()
        n1 = NovelUnderstander(home / "a", clock=clock, client=c1, enabled=True, prefer_novel=True)
        u1 = n1.understand(c, {}, [], prior=prior)
        c2 = FakeNovelClient()
        n2 = NovelUnderstander(home / "b", clock=clock, client=c2, enabled=True, prefer_novel=False)
        u2 = n2.understand(c, {}, [], prior=prior)
        result = dict(
            experiment="E2",
            prefer_true_calls=len(c1.calls),
            prefer_false_calls=len(c2.calls),
            prefer_true_got=u1 is not None,
            prefer_false_got=u2 is not None,
            ok=(len(c1.calls) == 1 and len(c2.calls) == 0 and u1 is not None and u2 is None),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
