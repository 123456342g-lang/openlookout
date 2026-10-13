from sprite.winprobe import WinProbe, CpuTracker, parse_tasklist
from sprite import risk as R


class FakePs:
    class _P:
        def __init__(s, pid, name, rss, ppid, cpu, cmd="", children=0): s.pid, s._n, s._r, s._pp, s._c, s._cmd, s._ch = pid, name, rss, ppid, cpu, cmd, children
        def oneshot(s):
            import contextlib; return contextlib.nullcontext()
        def cpu_times(s):
            class T: pass
            t = T(); t.user, t.system = s._c, 0; return t
        def name(s): return s._n + ".exe"
        def memory_info(s):
            class M: pass
            m = M(); m.rss = int(s._r * 2**20); return m
        def ppid(s): return s._pp
        def cmdline(s): return s._cmd.split()
        def cwd(s): return "C:\\proj"
        def children(s): return [0] * s._ch
    def __init__(self): self.t = 0; self.procs = {}
    def process_iter(self):
        return [FakePs._P(pid, n, r, pp, c(self.t) if callable(c) else c, cmd, ch) for pid, (n, r, pp, c, cmd, ch) in self.procs.items()]


class FakeWin:
    def __init__(s, wins, fg): s._w, s._fg = wins, fg
    def windows(s): return s._w
    def foreground_pid(s): return s._fg


class FakeAudio:
    def __init__(s, pids): s.p = pids
    def active_pids(s): return s.p


def mk():
    ps = FakePs(); clock = [0.0]
    ps.procs = {1: ("explorer", 100, 0, 5, "", 0), 5: ("chrome", 200, 0, 5.0, "chrome", 3),
                10: ("chrome", 900, 5, 100.0, "chrome --type=renderer", 0),            # 空闲
                11: ("chrome", 900, 5, lambda t: 100 + t * 0.5, "chrome --type=renderer", 0),   # 一直在用 CPU
                12: ("chrome", 900, 5, 100.0, "chrome --type=renderer", 0),            # 空闲，但在出声
                20: ("winword", 500, 1, 50.0, "", 0), 30: ("msedgewebview2", 300, 999, 10.0, "", 0)}      # 30 的父进程不存在
    w = FakeWin({20: [("论文 - Word *", True)], 1: [("桌面", True)]}, fg=1)
    pr = WinProbe(lambda: clock[0], psutil_mod=ps, windows=w, audio=FakeAudio({12}))
    return pr, ps, clock


def step(pr, ps, clock, dt):
    clock[0] += dt; ps.t = clock[0]; return {p.pid: p for p in pr.procs()[0]}


def test_idle_time_grows_only_with_observation_and_busy_resets():
    pr, ps, clock = mk()
    d = step(pr, ps, clock, 0); assert d[10].idle_s == 0
    d = step(pr, ps, clock, 1200); assert d[10].idle_s == 1200 and d[11].idle_s == 0
    d = step(pr, ps, clock, 900); assert d[10].idle_s == 2100


def test_window_foreground_audio_unsaved_orphan_info():
    pr, ps, clock = mk(); step(pr, ps, clock, 0); d = step(pr, ps, clock, 2400)
    assert d[20].has_window and d[20].title.endswith("*") and R.classify_proc(d[20]).level == "high"
    assert d[12].audio is True and R.classify_proc(d[12]).level == "high"
    assert d[10].audio is False and R.classify_proc(d[10]).level == "safe"          # 能判断出：空闲40分钟且没声音
    assert d[30].parent_alive is False
    assert d[1].foreground_tree and not d[10].foreground_tree


def test_foreground_tree_blocks_suspend():
    pr, ps, clock = mk(); pr.win = FakeWin({10: [("Tab", True)]}, fg=10); step(pr, ps, clock, 0); d = step(pr, ps, clock, 2400)
    assert d[10].foreground_tree and R.classify_proc(d[10]).level == "high"


def test_audio_unknown_requires_longer_idle_and_degrades():
    pr, ps, clock = mk(); pr.audio = FakeAudio(None); step(pr, ps, clock, 0)
    d = step(pr, ps, clock, 1000); assert d[10].audio is None and R.classify_proc(d[10]).level == "high"       # 空闲 1000s < 1800s
    d = step(pr, ps, clock, 1000); assert R.classify_proc(d[10]).level == "safe"


def test_ctypes_and_psutil_missing_falls_back_to_tasklist():
    csv_text = '"映像名称","PID","会话名","会话#","内存使用","状态","用户名","CPU 时间","窗口标题"\n"chrome.exe","10","Console","1","900,000 K","Running","u","0:10:00","N/A"\n"WINWORD.EXE","20","Console","1","500,000 K","Running","u","0:01:00","论文 - Word *"\n'
    rows = parse_tasklist(csv_text); assert rows[1]["title"].endswith("*") and rows[0]["cpu_s"] == 600 and abs(rows[0]["rss_mb"] - 878.9) < 1
    clock = [0.0]
    # 显式给出“拿不到音频”的后端，而不是靠 audio=None（那是“自动探测”，结果随本机装没装 pycaw 变，测试就不确定了）
    pr = WinProbe(lambda: clock[0], psutil_mod=False, windows=None, audio=FakeAudio(None), tasklist=lambda: csv_text); pr.ps = None; pr.layer = "tasklist"
    procs, _ = pr.procs(); assert len(procs) == 2 and procs[0].parent_alive is True and procs[0].audio is None
    assert all(R.classify_proc(p).level == "high" for p in procs)          # 信息不足 -> 全部不动
