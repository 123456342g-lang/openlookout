"""真实进程测试：Linux 上用真实子进程 + SIGSTOP/SIGCONT（PosixBackend）；Windows 路径用 ctypes 假对象验证调用序列。"""
import os, subprocess, sys, time, json, signal
from pathlib import Path
import pytest
from sprite.procctl import JournaledController, PosixBackend, WinBackend, resume_from_journal, DENY_NAMES

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="需要 /proc 与信号")


def state(pid):
    time.sleep(0.15)                                  # 信号异步送达
    return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]


@pytest.fixture
def dummies(tmp_path):
    ps = []
    def mk(name="chrome"):
        link = tmp_path / name
        if not link.exists(): link.symlink_to(sys.executable)
        p = subprocess.Popen([str(link), "-c", "import time;time.sleep(120)", "--type=renderer"]); ps.append(p); time.sleep(0.3); return p
    yield mk
    for p in ps:
        try: os.kill(p.pid, signal.SIGCONT); p.kill(); p.wait(timeout=5)
        except Exception: pass


@linux
def test_real_suspend_resume_and_journal(tmp_path, dummies):
    a, b = dummies(), dummies()
    c = JournaledController(tmp_path, spawn_watchdog=False)
    assert c.suspend(a.pid, "chrome", 300) and state(a.pid) == "T" and state(b.pid) != "T"
    assert str(a.pid) in json.loads((tmp_path / "suspended.json").read_text())
    assert a.pid in c.suspended
    assert c.resume(a.pid) and state(a.pid) != "T" and not c.suspended


@linux
def test_denylist_caps_and_self_protection(tmp_path, dummies):
    c = JournaledController(tmp_path, max_n=2, max_rss_mb=500, spawn_watchdog=False)
    py = dummies("python"); assert not c.suspend(py.pid, "python", 999) and state(py.pid) != "T"          # 黑名单
    assert not c.suspend(os.getpid(), "chrome", 100) and not c.suspend(os.getppid(), "chrome", 100)       # 自己/启动者
    for n in ("defender-helper", "code", "winword", "explorer", "msmpeng"): assert not c.suspend(py.pid, n, 100)
    ps = [dummies() for _ in range(3)]
    assert c.suspend(ps[0].pid, "chrome", 100) and c.suspend(ps[1].pid, "chrome", 100)
    assert not c.suspend(ps[2].pid, "chrome", 100) and state(ps[2].pid) != "T"                            # 数量上限
    c.resume_all()
    c2 = JournaledController(tmp_path, max_rss_mb=500, spawn_watchdog=False)
    assert c2.suspend(ps[0].pid, "chrome", 400) and not c2.suspend(ps[1].pid, "chrome", 200)              # 累计内存上限
    c2.resume_all(); assert all(state(p.pid) != "T" for p in ps)


@linux
def test_allow_only_and_pid_reuse_guard(tmp_path, dummies):
    a, b = dummies(), dummies()
    c = JournaledController(tmp_path, allow_only={a.pid}, spawn_watchdog=False)
    assert not c.suspend(b.pid, "chrome", 300) and c.suspend(a.pid, "chrome", 300)
    d = json.loads((tmp_path / "suspended.json").read_text()); d[str(a.pid)]["ident"] = "bogus"; (tmp_path / "suspended.json").write_text(json.dumps(d))      # 模拟 PID 被复用
    assert c.resume(a.pid) and state(a.pid) == "T"                                                           # 身份对不上：不去碰（日志清掉）
    os.kill(a.pid, signal.SIGCONT)


@linux
def test_dry_mode_touches_nothing(tmp_path, dummies):
    a = dummies(); c = JournaledController(tmp_path, live=False)
    assert c.suspend(a.pid, "chrome", 300) and state(a.pid) != "T" and c.would == [(a.pid, "chrome", 300)] and not (tmp_path / "suspended.json").exists()
    assert a.pid in c.suspended and c.resume(a.pid) and not c.suspended


@linux
def test_watchdog_resumes_after_sprite_crash(tmp_path, dummies):
    a = dummies()
    code = (f"import sys,os,time; sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r});"
            f"from sprite.procctl import JournaledController; c=JournaledController({str(tmp_path)!r}, allow_only={{{a.pid}}});"
            f"print(c.suspend({a.pid},'chrome',300), flush=True); time.sleep(60)")
    sp = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert sp.stdout.readline().strip() == "True"; time.sleep(0.5); assert state(a.pid) == "T"
    sp.kill(); sp.wait()                                                                                       # 强杀精灵（atexit 不会跑）
    for _ in range(40):
        if state(a.pid) != "T": break
        time.sleep(0.25)
    assert state(a.pid) != "T", "看门狗没有恢复"
    assert json.loads((tmp_path / "suspended.json").read_text()) == {}


@linux
def test_resume_all_cli_from_journal(tmp_path, dummies):
    a = dummies(); c = JournaledController(tmp_path, spawn_watchdog=False); c.suspend(a.pid, "chrome", 100); assert state(a.pid) == "T"
    r = subprocess.run([sys.executable, "-m", "sprite.procctl", "--journal", str(tmp_path / "suspended.json"), "--resume-all"], cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True)
    assert "已恢复 1" in r.stdout and state(a.pid) != "T"


def test_windows_backend_call_sequence_with_mocks(monkeypatch):
    calls = []
    class K:
        def OpenProcess(self, access, inh, pid): calls.append(("open", access, pid)); return 77
        def CloseHandle(self, h): calls.append(("close", h)); return 1
    class N:
        def NtSuspendProcess(self, h): calls.append(("susp", h)); return 0
        def NtResumeProcess(self, h): calls.append(("res", h)); return 0
    import types
    fake = types.SimpleNamespace(kernel32=K(), ntdll=N(), psapi=types.SimpleNamespace(EmptyWorkingSet=lambda h: calls.append(("trim", h)) or 1))
    import ctypes; monkeypatch.setattr(ctypes, "windll", fake, raising=False)
    b = WinBackend(); assert b.suspend(1234) and b.resume(1234) and b.trim(1234)
    assert calls[:3] == [("open", 0x0800, 1234), ("susp", 77), ("close", 77)] and ("res", 77) in calls and ("trim", 77) in calls
    assert not any(c[0] in ("kill", "terminate") for c in calls)                                              # 没有任何“结束进程”调用
    assert "python" in DENY_NAMES and "pythonw" in DENY_NAMES
