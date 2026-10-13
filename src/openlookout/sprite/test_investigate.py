"""investigate-then-act：假后端测试（假计划任务、假窗口观察、假系统视图、假进程控制）。"""
import json
from pathlib import Path
from sprite.framework import Engine, Registry
from sprite.investigate import ProcInfo, InvestigatorRegistry, Investigator, investigator_scenario
from sprite.scenarios import annoyance as A

XML = '''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>%s</Description><URI>%s</URI></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>2026-01-01T00:00:00</StartBoundary><Repetition><Interval>PT2M</Interval></Repetition></TimeTrigger></Triggers>
  <Actions Context="Author"><Exec><Command>%s</Command><Arguments>%s</Arguments></Exec></Actions>
</Task>'''


class Clock:
    def __init__(s, t=1_800_000_000.0): s.t = t
    def __call__(s): return s.t
    def sleep(s, d): s.t += d


class FakeView:
    def __init__(s, clock, procs=None):
        s.clock, s._procs, s.mt, s.heads, s.files, s.dirty, s.me = clock, procs or {}, {}, {}, set(), {}, 999999
    def now(s): return s.clock()
    def self_pid(s): return s.me
    def procs(s): return dict(s._procs)
    def open_files(s, pid): return []
    def newest_mtime(s, root, depth=3, cap=0):
        r = str(root).lower()
        return next((v for k, v in s.mt.items() if r.startswith(k.lower())), None)
    def git_root(s, path): return None
    def git_dirty(s, root): return None
    def read_head(s, path, n=4000): return s.heads.get(path, "")
    def exists(s, path): return path in s.files


class FakeBackend:
    def __init__(s, clock): s.clock, s.tasks, s.regs, s.on_start, s.fail_reg = clock, {}, [], None, False
    def add(s, path, xml, result=0): s.tasks[path] = A.TaskInfo(path, xml, 0.0, result, "Ready")
    def list_tasks(s): return list(s.tasks.values())
    def info(s, path): return s.tasks.get(path)
    def register(s, path, xml):
        if s.fail_reg: raise PermissionError("denied")
        s.regs.append((path, xml)); t = s.tasks[path]; t.xml = xml
    def start(s, path):
        t = s.tasks[path]; t.last_run = s.clock(); t.last_result = 0
        if s.on_start: s.on_start(path, t)


def popup_env(tmp_path, path, command, args, script="D:\\proj\\watch.ps1", head="# Watches the thing\n", hits=4, visible=True, desc="watch"):
    clock = Clock(); view = FakeView(clock); view.files.add(script); view.heads[script] = head
    be = FakeBackend(clock); be.add(path, XML % (desc, path, command, args))
    obs = A.ConsoleObserver(tmp_path / "h"); (tmp_path / "h").mkdir(exist_ok=True)
    cmd = [command] + A.tokens(args)
    for i in range(hits): obs.add(A.Launch(clock() - 600 + i * 120, 100 + i, 1, cmd, visible=visible, parent="svchost.exe"))
    return clock, view, be, obs


def mk(tmp_path, clock, view, be, obs, live=True, procs=True, ctl=None):
    home = tmp_path / "h"; kit = A.PopupKit(be, obs, view, home, clock, conhost=r"C:\Windows\System32\conhost.exe", sleep=clock.sleep)
    pk = A.ProcKit(view, ctl or FakeCtl(), home, clock) if procs else None
    ireg = A.register_all(InvestigatorRegistry(), kit, pk, clock, poll_s=0)
    inv = Investigator(ireg, view, home, clock); sc = investigator_scenario(ireg, inv, live=live, log=lambda *a: None)
    reg = Registry(); reg.register(sc); (home / "eh").mkdir(parents=True, exist_ok=True); return Engine(reg, home / "eh", clock=clock), kit, pk, sc, home


class FakeCtl:
    def __init__(s): s.susp = set(); s.dead = set()
    def get(s, pid, ct): return None if pid in s.dead else True
    def suspend(s, pid, ct): s.susp.add(pid); return True
    def resume(s, pid, ct): s.susp.discard(pid); return True
    def suspended(s, pid, ct): return pid in s.susp


PS = ("powershell.exe", '-NoProfile -File "D:\\proj\\watch.ps1" -Port 1')


def test_recurring_visible_detected_fixed_and_verified(tmp_path):
    clock, view, be, obs = popup_env(tmp_path, "\\Mine", *PS); e, kit, _, sc, home = mk(tmp_path, clock, view, be, obs)
    orig = be.tasks["\\Mine"].xml
    outs = e.step(None); acted = [a for o in outs for a in o.acted]
    assert len(acted) == 1 and acted[0].kind == "popup_headless"
    assert "--headless" in be.tasks["\\Mine"].xml and "conhost.exe" in be.tasks["\\Mine"].xml and "watch.ps1" in be.tasks["\\Mine"].xml
    assert (home / "inv_journal").glob("Mine*") and any(home.joinpath("inv_journal").glob("*Mine*.xml"))
    rec = [json.loads(l) for l in (home / "understandings.jsonl").read_text("utf-8").splitlines()]
    assert rec[0]["state"] in ("in_use", "under_development") and rec[0]["act"] and rec[0]["evidence"]
    assert A.parse_task(be.tasks["\\Mine"].xml)["command"].lower().endswith("conhost.exe")
    # 撤销：原样还原
    assert e.undo(acted[0].id) and be.tasks["\\Mine"].xml == orig


def test_already_hidden_ignored(tmp_path):
    clock, view, be, obs = popup_env(tmp_path, "\\Mine", "conhost.exe", '--headless powershell.exe -NoProfile -File "D:\\proj\\watch.ps1"')
    e, *_ = mk(tmp_path, clock, view, be, obs)
    assert [a for o in e.step(None) for a in o.acted] == [] and not be.regs


def test_invisible_or_oneoff_ignored(tmp_path):
    """可见次数不够、且任务不是周期性重复 → 不动。"""
    one_xml = """<?xml version=\"1.0\" encoding=\"UTF-16\"?>
<Task version=\"1.2\" xmlns=\"http://schemas.microsoft.com/windows/2004/02/mit/task\">
  <RegistrationInfo><Description>watch</Description><URI>\\Mine</URI></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>2026-01-01T00:00:00</StartBoundary></TimeTrigger></Triggers>
  <Actions Context=\"Author\"><Exec><Command>%s</Command><Arguments>%s</Arguments></Exec></Actions>
</Task>""" % PS
    for i, kw in enumerate((dict(hits=2), dict(visible=False))):
        sub = tmp_path / ("c%d" % i); sub.mkdir(parents=True, exist_ok=True)
        clock, view, be, obs = popup_env(sub, "\\Mine", *PS, **kw)
        be.tasks["\\Mine"].xml = one_xml
        e, *_ = mk(sub, clock, view, be, obs)
        assert [a for o in e.step(None) for a in o.acted] == [] and not be.regs


def test_periodic_task_without_enough_flashes_still_fixed(tmp_path):
    """带 Repetition 的控制台任务：即使可见闪窗不够 3 次，也应立案并改成无窗口。"""
    clock, view, be, obs = popup_env(tmp_path, "\\Mine", *PS, hits=1, visible=False)
    e, *_ = mk(tmp_path, clock, view, be, obs)
    acted = [a for o in e.step(None) for a in o.acted]
    assert len(acted) == 1 and acted[0].kind == "popup_headless"


def test_protected_and_vendor_refused(tmp_path):
    for path, script in (("\\Microsoft\\Windows\\X", "D:\\proj\\watch.ps1"), ("\\NvDriverUpdateCheck", "D:\\proj\\watch.ps1"), ("\\Vendor", "C:\\Program Files\\V\\upd.ps1")):
        clock, view, be, obs = popup_env(tmp_path, path, "powershell.exe", f'-NoProfile -File "{script}"', script=script)
        e, *_, home = mk(tmp_path, clock, view, be, obs)
        assert [a for o in e.step(None) for a in o.acted] == [] and not be.regs, path
        st = [json.loads(l)["state"] for l in (home / "understandings.jsonl").read_text("utf-8").splitlines() if json.loads(l)["key"] == "task:" + path]; assert st and st[-1] in ("protected", "vendor"), (path, st)


def test_interactive_script_refused(tmp_path):
    clock, view, be, obs = popup_env(tmp_path, "\\Mine", *PS, head="# x\n$a = Read-Host 'go?'\n"); e, *_ = mk(tmp_path, clock, view, be, obs)
    assert [a for o in e.step(None) for a in o.acted] == [] and not be.regs


def test_verify_failure_rolls_back(tmp_path):
    clock, view, be, obs = popup_env(tmp_path, "\\Mine", *PS); e, kit, *_ = mk(tmp_path, clock, view, be, obs); orig = be.tasks["\\Mine"].xml
    be.on_start = lambda p, t: obs.add(A.Launch(clock(), 7, 1, ["conhost.exe", "--headless"] + [PS[0]] + A.tokens(PS[1]), visible=True, parent="svchost.exe"))
    outs = e.step(None)
    assert not [a for o in outs for a in o.acted] and be.tasks["\\Mine"].xml == orig and len(be.regs) == 2


def test_task_failure_after_change_rolls_back(tmp_path):
    clock, view, be, obs = popup_env(tmp_path, "\\Mine", *PS); e, *_ = mk(tmp_path, clock, view, be, obs); orig = be.tasks["\\Mine"].xml
    def bad(p, t): t.last_result = 1
    be.on_start = bad; e.step(None); assert be.tasks["\\Mine"].xml == orig


def test_no_permission_skips(tmp_path):
    clock, view, be, obs = popup_env(tmp_path, "\\Mine", *PS); e, *_ = mk(tmp_path, clock, view, be, obs); be.fail_reg = True
    assert [a for o in e.step(None) for a in o.acted] == []


def test_dry_mode_investigates_only(tmp_path):
    clock, view, be, obs = popup_env(tmp_path, "\\Mine", *PS); e, kit, _, sc, home = mk(tmp_path, clock, view, be, obs, live=False)
    assert [a for o in e.step(None) for a in o.acted] == [] and not be.regs and sc.plans
    assert (home / "understandings.jsonl").exists()


# ---------- 陈旧进程：靠证据，不靠名字 ----------
def P(pid, ppid, name, cmd, t, cwd="E:\\Proj", rss=80, ports=None, win=False):
    return ProcInfo(pid, ppid, name, "D:\\py\\" + name, ["D:\\py\\" + name] + cmd, cwd, t, rss, 0, ports or [], win)


def proc_world(tmp_path, procs, dev_age_s=3600.0):
    clock = Clock(); now = clock(); view = FakeView(clock, {p.pid: p for p in procs(now)}); view.mt["e:\\proj"] = now - dev_age_s; ctl = FakeCtl()
    e, kit, pk, sc, home = mk(tmp_path, clock, view, FakeBackend(clock), A.ConsoleObserver(tmp_path / "h"), ctl=ctl); (tmp_path / "h").mkdir(exist_ok=True)
    return e, view, ctl, home


def test_old_orphan_instance_suspended_new_and_dev_untouched(tmp_path):
    H = 3600
    def procs(n): return [
        P(10, 5, "pythonw.exe", ["-m", "sprite.run", "--home", "E:\\h"], n - 5 * H),                   # 旧实例：父进程已不在
        P(11, 6, "pythonw.exe", ["-m", "sprite.run", "--home", "E:\\h"], n - 600),                     # 新实例（父 6 在）
        P(6, 1, "cmd.exe", ["/c", "x.bat"], n - 600),
        P(12, 7, "python.exe", ["demo_private\\sprite_t3_check.py"], n - 120),                           # 开发中的检查脚本：别碰
        P(13, 7, "python.exe", ["-m", "pytest", "sprite"], n - 60),                                     # 别的 agent 在跑的 pytest
        P(7, 1, "powershell.exe", ["-NoExit"], n - 7200)]
    e, view, ctl, home = proc_world(tmp_path, procs); view.me = 11
    acted = [a for o in e.step(None) for a in o.acted]
    assert [a.name for a in acted] == ["挂起 10"] and ctl.susp == {10}
    assert e.undo(acted[0].id) and ctl.susp == set()
    recs = [json.loads(l) for l in (home / "understandings.jsonl").read_text("utf-8").splitlines()]
    assert any(r["state"] == "stale_duplicate" and r["act"] for r in recs) and not any(r["key"].startswith("proc:12") or r["key"].startswith("proc:13") for r in recs if r["act"])


def test_live_parent_or_dependents_or_young_are_not_touched(tmp_path):
    H = 3600
    def procs(n): return [
        P(10, 5, "python.exe", ["srv.py", "--p", "1"], n - 5 * H, ports=[8000]),                       # 有监听端口：有人依赖
        P(11, 6, "python.exe", ["srv.py", "--p", "1"], n - 600),
        P(20, 8, "python.exe", ["w.py", "--p", "1"], n - 5 * H),                                        # 父进程还活着：可能是它在管
        P(21, 8, "python.exe", ["w.py", "--p", "1"], n - 600), P(8, 1, "cmd.exe", [], n - 6 * H),
        P(30, 5, "python.exe", ["j.py"], n - 100), P(31, 5, "python.exe", ["j.py"], n - 20)]            # 刚启动：可能在重启中
    e, view, ctl, home = proc_world(tmp_path, procs)
    assert [a for o in e.step(None) for a in o.acted] == [] and not ctl.susp


def test_self_never_touched_even_if_older(tmp_path):
    def procs(n): return [P(10, 5, "python.exe", ["-m", "sprite.run"], n - 9999), P(11, 6, "python.exe", ["-m", "sprite.run"], n - 600)]
    e, view, ctl, home = proc_world(tmp_path, procs); view.me = 10
    assert [a for o in e.step(None) for a in o.acted] == [] and not ctl.susp


def test_abandoned_orphan_needs_untouched_project(tmp_path):
    def procs(n): return [P(10, 5, "python.exe", ["old.py"], n - 20 * 3600)]
    e, view, ctl, home = proc_world(tmp_path, procs, dev_age_s=30 * 86400)
    acted = [a for o in e.step(None) for a in o.acted]; assert [a.name for a in acted] == ["挂起 10"]
    e, view, ctl, home = proc_world(tmp_path / "b", procs, dev_age_s=3600)       # 项目刚被改过 -> 当作开发中
    assert [a for o in e.step(None) for a in o.acted] == [] and not ctl.susp


def test_resume_all_journal(tmp_path):
    def procs(n): return [P(10, 5, "python.exe", ["old.py"], n - 20 * 3600)]
    e, view, ctl, home = proc_world(tmp_path, procs, dev_age_s=30 * 86400); e.step(None)
    kit = A.ProcKit(view, ctl, home); assert ctl.susp == {10} and kit.resume_all() == 1 and ctl.susp == set()

def test_young_dev_script_of_same_family_does_not_make_live_instance_stale(tmp_path):
    def procs(n): return [P(10, 5, "pythonw.exe", ["-m", "sprite.demo_live.live", "--live"], n - 1800),
                          P(11, 6, "python.exe", ["-m", "sprite.demo_live.dry_run"], n - 15)]          # 别的 agent 刚启动的开发脚本，同家族
    e, view, ctl, home = proc_world(tmp_path, procs)
    assert [a for o in e.step(None) for a in o.acted] == [] and not ctl.susp


def test_old_preview_superseded_by_stable_family_member(tmp_path):
    H = 3600
    def procs(n): return [P(10, 5, "pythonw.exe", ["-m", "sprite.preview", "--home", "E:\\old"], n - 6 * H),
                          P(11, 6, "pythonw.exe", ["-m", "sprite.demo_live.live", "--live"], n - 3 * H), P(6, 1, "cmd.exe", [], n - 3 * H)]
    e, view, ctl, home = proc_world(tmp_path, procs)
    acted = [a for o in e.step(None) for a in o.acted]; assert [a.name for a in acted] == ["挂起 10"] and ctl.susp == {10}
