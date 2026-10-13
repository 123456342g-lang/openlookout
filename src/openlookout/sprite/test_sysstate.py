"""sysstate 合格判定与内存压力的测试：判定用纯函数，真实采集另测。"""
import json, os, subprocess, sys, time
import pytest
from pathlib import Path
from sprite import sysstate as ss

nt = pytest.mark.skipif(os.name != "nt", reason="需要 Windows")


def rec(**over):
    base = dict(pid=100, ppid=1, name="idle_bg", session=1, username="PC\\q", create=1000.0,
                rss_mb=512.0, cpu_pct=0.1, children=0, openable=True, idle_s=600.0)
    base.update(over)
    return base


def ctx(**over):
    base = dict(now=2000.0, self_pid=1, own_tree={1}, sprite_ancestors=set(), session=1,
                username="PC\\q", shell=2, console=set(), fg=3, audio=set(),
                parents={100: 1, 1: 0, 3: 1, 7: 1}, windows={}, net=lambda pid: 0)
    base.update(over)
    return base


def why(r, c, cfg=None):
    return ss.decide(r, c, cfg or ss.DEFAULTS)


def test_good_candidate_passes():
    assert why(rec(), ctx()) is None
    assert why(rec(), ctx(audio=None)) == "audio_unknown"      # 不知道就没在放 -> 全部不合格


@pytest.mark.parametrize("r,c,reason", [
    (rec(pid=1), ctx(), "host"),                               # 自己
    (rec(pid=7, ppid=70), ctx(own_tree={1, 7, 70}), "host"),   # 自己的子树
    (rec(pid=7, ppid=70), ctx(sprite_ancestors={70}), "host"),  # 精灵的宿主链
    (rec(session=0), ctx(), "system"),
    (rec(username="NT AUTHORITY\\SYSTEM"), ctx(), "system"),
    (rec(pid=2), ctx(), "system"),                              # 桌面/shell 窗口属主
    (rec(openable=False), ctx(), "protected"),
    (rec(pid=3), ctx(), "foreground"),
    (rec(pid=5), ctx(audio={5}), "audio"),
    (rec(pid=5), ctx(windows={5: {"visible": True, "unsaved": False, "console": False}}), "window"),
    (rec(pid=5), ctx(windows={5: {"visible": False, "unsaved": True, "console": False}}), "unsaved"),
    (rec(pid=5), ctx(windows={5: {"visible": True, "unsaved": False, "console": True}}), "terminal"),
    (rec(pid=5), ctx(console={5}), "terminal"),
    (rec(pid=5, ppid=6), ctx(parents={5: 6, 6: 1}, windows={6: {"visible": True, "unsaved": False, "console": False}}), "host_app"),
    (rec(children=2), ctx(), "has_children"),
    (rec(idle_s=10), ctx(), "busy"),
    (rec(create=1990.0), ctx(), "young"),
    (rec(rss_mb=20), ctx(), "small"),
    (rec(cpu_pct=80.0), ctx(), "busy"),
    (rec(pid=5), ctx(net=lambda pid: 4), "network"),
])
def test_each_gate_rejects(r, c, reason):
    assert why(r, c) == reason


def test_transparent_ancestor_not_host_app():
    """精灵自己的宿主（终端/IDE）不算“宿主应用”，否则在终端里跑就永远挑不到候选。"""
    r = rec(pid=5, ppid=6)
    c = ctx(parents={5: 6, 6: 1}, sprite_ancestors={1},
            windows={6: {"visible": True, "unsaved": False, "console": False}})
    assert why(r, c) is None


def test_network_gate_is_lazy():
    calls = []
    c = ctx(net=lambda pid: calls.append(pid) or 0)
    assert why(rec(idle_s=1), c) == "busy"                  # 前面的门没过，不该去查网络
    assert calls == []
    assert why(rec(), c) is None
    assert calls == [100]


def test_eat_memory_raises_pressure_and_releases():
    from sprite import winprobe
    before = winprobe.memory()
    block = ss.eat_memory(64)
    mid = winprobe.memory()
    assert before["available"] - mid["available"] >= 32, "吃掉的内存应该让可用内存下降"
    del block
    end = time.time() + 10
    while time.time() < end and winprobe.memory()["available"] < before["available"] - 8:
        time.sleep(0.2)
    assert winprobe.memory()["available"] >= before["available"] - 8


@nt
def test_assess_only_reports_never_suspends(tmp_path):
    home = tmp_path / "home"
    out = ss.assess(home=home, warmup=0.2, only_pids=[os.getpid()])
    assert out["pressure"] in ("ok", "low", "critical")
    assert out["candidates"] == []
    assert "rejected" in out
    assert out["rejected"].get(str(os.getpid())) in ("host", "self", None) or str(os.getpid()) in out["own_tree"]
    from sprite import procctl
    assert procctl.pending(home) == [], "--assess 只评估，不能动任何进程"


@nt
def test_cli_assess_json(tmp_path):
    root = str(Path(ss.__file__).resolve().parent.parent)
    r = subprocess.run([sys.executable, "-m", "sprite.sysstate", "--assess", "--json",
                        "--home", str(tmp_path / "home"), "--warmup", "0"],
                       capture_output=True, text=True, cwd=root, timeout=120)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert {"pressure", "memory", "candidates", "rejected"} <= set(data)


@nt
def test_live_refuses_without_pressure(tmp_path):
    """没有内存压力就不许 --live 动手（状态变化驱动，不是定时清理）。"""
    root = str(Path(ss.__file__).resolve().parent.parent)
    home = tmp_path / "home"
    # 只有压力为 ok 时才应拒绝；当前机器压力未知，所以用 --assess 的结果判断
    out = ss.assess(home=home, warmup=0.0, only_pids=[os.getpid()])
    if out["pressure"] == "ok":
        r = subprocess.run([sys.executable, "-m", "sprite.sysstate", "--live", "--json",
                            "--home", str(home), "--warmup", "0", "--pids", str(os.getpid())],
                           capture_output=True, text=True, cwd=root, timeout=120)
        assert r.returncode != 0 or json.loads(r.stdout).get("suspended") == 0
        from sprite import procctl
        assert procctl.pending(home) == []
