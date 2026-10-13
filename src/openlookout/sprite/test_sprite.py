import json, os, time
from pathlib import Path
from sprite import config
from sprite.core import Sprite, in_quiet
from datetime import datetime

NOON = datetime(2026, 10, 9, 12, 0).timestamp()


def snap(root):
    return sorted((str(p.relative_to(root)), p.read_bytes() if p.is_file() else None) for p in Path(root).rglob("*"))


def mk(tmp, watch, **over):
    cfg = json.loads(json.dumps(config.DEFAULTS)); cfg.update(dict(dict(quiet_hours=None, settle_s=60, watch=watch), **over))
    clock = [NOON]
    s = Sprite(cfg, tmp / "home", clock=lambda: clock[0])
    return s, clock


def put(p, text, age=1000):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    os.utime(p, (NOON - age, NOON - age))


def test_end_to_end_scaffold(tmp_path):
    docs = tmp_path / "docs"
    put(docs / "lab6/data/a.csv", "x"); put(docs / "lab6/figs/f.png", "y")
    s, clock = mk(tmp_path, {str(docs): ["scaffold"]})
    assert s.tick() == []                       # 基线
    (docs / "lab7").mkdir()                     # 模拟用户新建目录
    before = snap(docs)
    msgs = s.tick()
    assert len(msgs) == 1 and "lab7" in msgs[0]["text"] and msgs[0]["verified"]
    assert (docs / "lab7/data").is_dir() and (docs / "lab7/figs").is_dir() and (docs / "lab7/README.md").exists()
    assert s.tick() == []                       # 幂等
    assert s.undo(msgs[0]["id"])
    assert (docs / "lab7").is_dir() and not list((docs / "lab7").iterdir())
    assert snap(docs) == before
    assert s.messages()[-1]["kind"] == "undo"
    s.tick(); assert not (docs / "lab7/README.md").exists()   # 撤销后不再重做


def test_dedupe_waits_for_settle_and_undo_restores_bytes(tmp_path):
    dl = tmp_path / "dl"
    put(dl / "paper.pdf", "SAME", 5000)
    s, clock = mk(tmp_path, {str(dl): ["dedupe"]})
    s.tick()
    put(dl / "paper (1).pdf", "SAME", 5)        # 刚下载完，还没稳定
    before = snap(dl)
    assert s.tick() == [] and snap(dl) == before
    clock[0] += 120; os.utime(dl / "paper (1).pdf", (NOON - 5, NOON - 5))
    msgs = s.tick()
    assert len(msgs) == 1 and (dl / "_dupes/paper (1).pdf").read_text() == "SAME"
    assert not (dl / "paper (1).pdf").exists() and (dl / "paper.pdf").exists()   # 没有删除
    assert s.undo(msgs[0]["id"]) and snap(dl) == before


def test_versioning_needs_three(tmp_path):
    d = tmp_path / "d"
    put(d / "报告.docx", "1", 900); put(d / "报告_最终.docx", "2", 800)
    s, _ = mk(tmp_path, {str(d): ["versioning"]}); s.tick()
    put(d / "报告_最终版(1).docx", "3", 700)
    before = snap(d)
    msgs = s.tick()
    assert len(msgs) == 1 and (d / "报告_v03.docx").read_text() == "3"
    assert s.undo(msgs[0]["id"]) and snap(d) == before


def test_policy_quiet_cap_kill(tmp_path):
    assert in_quiet({"quiet_hours": ["23:00", "08:00"]}, datetime(2026, 1, 1, 2, 0))
    assert not in_quiet({"quiet_hours": ["23:00", "08:00"]}, datetime(2026, 1, 1, 12, 0))
    dl = tmp_path / "dl"; put(dl / "a.txt", "A", 999)
    # 静默时段：不动手
    s, _ = mk(tmp_path, {str(dl): ["dedupe"]}, quiet_hours=["00:00", "23:59"]); s.tick()
    put(dl / "b.txt", "A", 999); before = snap(dl)
    assert s.tick() == [] and snap(dl) == before
    # 关停开关
    s2, _ = mk(tmp_path / "x", {str(dl): ["dedupe"]}); s2.tick(); (s2.home / "KILL").write_text("1")
    assert s2.tick() == [] and snap(dl) == before
    # 每日上限
    s3, _ = mk(tmp_path / "y", {str(dl): ["dedupe"]}, daily_cap=0); s3.tick()
    assert s3.tick() == [] and snap(dl) == before


def test_never_touches_outside_or_overwrites(tmp_path):
    from sprite.core import policy_check, Refused
    import pytest
    cfg = config.DEFAULTS
    with pytest.raises(Refused): policy_check(tmp_path, [dict(op="delete", dst="a")], cfg)
    with pytest.raises(Exception): policy_check(tmp_path, [dict(op="write", dst="../evil", content="x")], cfg)
    put(tmp_path / "a", "1")
    with pytest.raises(Exception): policy_check(tmp_path, [dict(op="write", dst="a", content="x")], cfg)


def test_action_is_reported_by_brain_in_context(tmp_path):
    docs = tmp_path / "docs"
    put(docs / "lab6/data/a.csv", "x"); put(docs / "lab6/figs/f.png", "y")
    s, clock = mk(tmp_path, {str(docs): ["scaffold"]})
    s.tick()
    (docs / "lab7").mkdir()
    s.tick()                                     # 动手（写入 action 事件）
    put(docs / "lab6/data/b.csv", "z", 0)        # 用户还在干活 -> present
    s.tick()
    clock[0] += 400
    msgs = s.tick() + s.tick()
    say = [m for m in msgs if m["kind"] == "say"]
    assert say and say[0]["topic"] == "report" and say[0]["action_id"]
    assert s.undo(say[0]["action_id"]) and not (docs / "lab7/README.md").exists()
