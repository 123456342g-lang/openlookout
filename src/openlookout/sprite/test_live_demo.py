"""端到端（无界面）：真实内存分配 -> 真实压力检测 -> 真实挂起（SIGSTOP，只针对测试起的假浏览器进程）-> 沙箱文件隔离 -> 一次批量提问 -> 同意 -> 撤销。
Windows 的 ctypes 路径见 test_procctl 的 mock 测试。"""
import json, os, signal, subprocess, sys, time
from pathlib import Path
import pytest
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="需要 /proc 与信号")
os.environ["SPRITE_FORCE_WINPROBE"] = "1"; os.environ["SPRITE_DEMO_ASSUME_PRESENT"] = "1"
from sprite import risk as R
from sprite.demo_live import live, stage_demo, common
from sprite.demo_live.eat_memory import Eater


@pytest.fixture(autouse=True)
def _restore_scale():
    yield; R.PROC_IDLE_SCALE = 1.0


def state(pid):
    time.sleep(0.1); return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]


def spawn(tmp, name, mb=220, spin=False):
    link = tmp / "bin" / name; link.parent.mkdir(exist_ok=True)
    if not link.exists(): link.symlink_to(sys.executable)
    code = f"b=bytearray({mb}*2**20); b[::4096]=b'x'*len(range(0,len(b),4096))\nimport time\n" + ("while True: pass" if spin else "time.sleep(300)")
    return subprocess.Popen([str(link), "-c", code, "--type=renderer"])


def pump(s, secs, until):
    t0 = time.time()
    while time.time() - t0 < secs:
        s.tick()
        if until(): return True
        time.sleep(0.4)
    return False


def test_real_pressure_to_real_suspend_to_undo(tmp_path):
    sb, home = tmp_path / "sb", tmp_path / "home"; home.mkdir(); stage_demo.stage(sb); man = json.loads((sb / "_manifest.json").read_text())
    good = [spawn(tmp_path, "chrome") for _ in range(2)]
    busy, ide, py = spawn(tmp_path, "chrome", spin=True), spawn(tmp_path, "code"), spawn(tmp_path, "python")
    allp = good + [busy, ide, py]; time.sleep(2.5)
    try:
        total, avail = common.mem_now()
        (home / "demo_live.json").write_text(json.dumps(dict(mem_warn_gb=(avail - 700) / 1024, extra_cache_dirs=[], max_suspend=6, max_suspend_mb=4096)))
        s, ctrl, dc = live.build(home, sb, live=True, log=lambda *a: None, allow_only={p.pid for p in allp})
        R.PROC_IDLE_SCALE = 0.004                                                       # 测试里不等分钟级
        live.presence_hook(s, every=0.5)
        msgs = []; s.on_message = lambda m: msgs.append(m)
        for _ in range(12): s.tick(); time.sleep(0.5)                                  # 建立空闲基线；此时没有压力
        assert not ctrl.suspended and common.mem_now()[1] > avail - 400
        eater = Eater(leave_gb=1.5, mb=1100)
        while eater.step(): pass                                                        # 真实占用 1.1GB
        assert common.mem_now()[1] < avail - 900
        assert pump(s, 40, lambda: any(m.get("kind") == "action" for m in msgs)), [m.get("text") for m in msgs]
        sus = {p.pid for p in allp if state(p.pid) == "T"}
        assert sus == {p.pid for p in good}, (sus, {p.pid: p.args for p in allp})       # 只挂起空闲的两个“浏览器后台标签”；忙的、code、python 都没动
        assert set(ctrl.suspended) == sus
        assert not any(m.get("topic") == "resource_ask" for m in msgs)                 # 没有任何询问
        st = stage_demo.check(sb)
        assert st["safe_moved"] == st["safe_total"] and 1 <= st["risky_moved"] < st["risky_total"] and st["traps_intact"] == st["traps_total"], st      # 有硬证据的直接收起（有逐字节副本的大文件），拿不准的（查不到来源的安装包）不动，陷阱字节不变
        acts = [m for m in s.messages() if m["kind"] == "action" and m["status"] == "done"]
        assert acts and all(len(m["text"]) <= 40 for m in acts), [m["text"] for m in acts]
        assert all([s.undo(m["id"]) for m in acts])                                       # 每条汇报都有撤销；全撤销后全部还原
        st = stage_demo.check(sb); assert st["all_restored"], st                        # 字节级还原
        assert all(state(p.pid) != "T" for p in allp) and not ctrl.suspended            # 进程全部恢复
        eater.release()
    finally:
        for p in allp:
            try: os.kill(p.pid, signal.SIGCONT); p.kill(); p.wait(5)
            except Exception: pass


def test_dry_mode_never_touches_processes(tmp_path):
    sb, home = tmp_path / "sb", tmp_path / "home"; home.mkdir(); stage_demo.stage(sb)
    good = [spawn(tmp_path, "chrome") for _ in range(2)]; time.sleep(2.5)
    try:
        total, avail = common.mem_now()
        (home / "demo_live.json").write_text(json.dumps(dict(mem_warn_gb=(avail - 700) / 1024, extra_cache_dirs=[], max_suspend=6, max_suspend_mb=4096)))
        s, ctrl, dc = live.build(home, sb, live=False, log=lambda *a: None); R.PROC_IDLE_SCALE = 0.004
        ctrl.allow_only = {p.pid for p in good}
        for _ in range(10): s.tick(); time.sleep(0.4)
        eater = Eater(1.5, 1100)
        while eater.step(): pass
        for _ in range(15): s.tick(); time.sleep(0.4)
        assert all(state(p.pid) != "T" for p in good) and not (home / "suspended.json").exists()
        assert {w[0] for w in ctrl.would} == {p.pid for p in good}                       # 干跑：只记下了“将会挂起”
        assert any("干跑" in m.get("text", "") for m in s.messages() if m["kind"] == "action")
        eater.release()
    finally:
        for p in good: p.kill(); p.wait(5)
