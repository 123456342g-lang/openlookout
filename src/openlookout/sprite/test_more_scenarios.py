"""T6 对抗测试：browser_tabs / battery_prewarm / homework_env_prep 三个新场景 + 真实控制器 win_ctrl。
验收口径：
- 数据缺（getattr 拿不到）就静默，绝不误报；
- 动作必须可整份撤销，撤销只动我们自己创建的东西；
- 失败必须回滚，不留半成品、不崩溃；
- 场景的「预警」必须通过安全可逆动作表达（框架只会为 acted 的动作出声）。"""
from __future__ import annotations
import json, shutil, time
from pathlib import Path
from types import SimpleNamespace
import pytest

from .framework import Registry, Engine
from .risk import Env
from .sysstate import FakeController, Proc
from .scenarios import more
from .scenarios.win_ctrl import WindowsController, Composite


def mk_world(tmp, env=None, ctrl=None, snap=None, home=None):
    from .scenarios.resource import World
    return World(env=env or Env(now=time.time()), q=None, ctrl=ctrl or FakeController(),
                 home=home or Path(tmp), snap=snap)


def step(reg, world, home):
    return Engine(reg, Path(home)).step(world)


def acted_kinds(outs):
    return [a.kind for o in outs for a in o.acted]


# ================================================================ browser_tabs
def tabs_snap(n, oldest=5):
    tabs = [dict(url=f"https://t{i}.example", title=f"Tab {i}", age_s=0) for i in range(n)]
    for i in range(oldest):                       # 最老的几个标上年龄，排序后应排在前面
        tabs[i]["age_s"] = 10_000 + i
    return SimpleNamespace(tabs=tabs, procs=[])


def test_tabs_archives_oldest_extra_and_undo(tmp_path):
    snap = tabs_snap(30, oldest=5)                # 超额 5 个
    w = mk_world(tmp_path, snap=snap)
    reg = Registry(); reg.register(more.browser_tabs(limit=25))
    eng = Engine(reg, tmp_path)
    outs = eng.step(w)
    assert "tab_archive" in acted_kinds(outs)
    a = outs[0].acted[0]
    f = Path(a.result["path"])
    assert f.exists() and f.name.startswith("tabs_archive_")
    lines = f.read_text("utf-8").splitlines()
    assert len(lines) == 5                        # 只存最老的 5 个超额标签
    assert "t4.example" in lines[0]               # 年龄最大的最老标签排最前
    assert all(f"t{i}.example" in "\n".join(lines) for i in range(5))  # 5 个最老的全部存档
    # 撤销：删掉的只是我们自己的档案文件
    assert eng.undo(a.id)
    assert not f.exists()


def test_tabs_archive_undo_same_engine(tmp_path):
    snap = tabs_snap(30, oldest=5)
    w = mk_world(tmp_path, snap=snap)
    reg = Registry(); reg.register(more.browser_tabs(limit=25))
    eng = Engine(reg, tmp_path)
    outs = eng.step(w)
    assert "tab_archive" in acted_kinds(outs)
    a = outs[0].acted[0]
    assert eng.undo(a.id)
    assert not Path(a.result["path"]).exists()


def test_tabs_never_closes_tabs(tmp_path):
    snap = tabs_snap(30, oldest=5)
    w = mk_world(tmp_path, snap=snap)
    reg = Registry(); reg.register(more.browser_tabs(limit=25))
    step(reg, w, tmp_path)
    assert len(w.snap.tabs) == 30                 # 存档只是存档，一个标签都不关


def test_tabs_under_limit_silent(tmp_path):
    w = mk_world(tmp_path, snap=tabs_snap(10))
    reg = Registry(); reg.register(more.browser_tabs(limit=25))
    assert step(reg, w, tmp_path) == []


def test_tabs_missing_data_silent(tmp_path):
    w = mk_world(tmp_path, snap=SimpleNamespace(procs=[]))   # 没有 tabs 字段
    reg = Registry(); reg.register(more.browser_tabs())
    assert step(reg, w, tmp_path) == []


def test_tabs_dict_shape(tmp_path):
    snap = SimpleNamespace(procs=[], tabs={"chrome": [{"url": "a", "age_s": 500}], "msedge": [{"url": "b", "age_s": 5}] * 30})
    w = mk_world(tmp_path, snap=snap)
    reg = Registry(); reg.register(more.browser_tabs(limit=25))
    outs = step(reg, w, tmp_path)
    assert "tab_archive" in acted_kinds(outs)


# ================================================================ battery_prewarn
def bat_snap(pct, charging, procs):
    return SimpleNamespace(battery=(pct, charging), procs=procs)


def renderer(pid):
    return Proc(pid=pid, name="chrome", rss_mb=300, idle_s=3600, has_window=False,
                foreground_tree=False, cmdline="chrome --type=renderer", children=0)


def busy_proc(pid, name="makemkv"):
    return Proc(pid=pid, name=name, rss_mb=1200, busy_s=900, idle_s=0, children=0)


def test_battery_low_suspends_idle_and_resume(tmp_path):
    w = mk_world(tmp_path, snap=bat_snap(15, False, [renderer(1), busy_proc(2)]))
    reg = Registry(); reg.register(more.battery_prewarn(threshold=20))
    eng = Engine(reg, tmp_path)
    outs = eng.step(w)
    kinds = acted_kinds(outs)
    assert "battery_suspend" in kinds
    assert len([k for k in kinds if k == "battery_suspend"]) == 1   # 只挂起可安全处理的那个
    assert 1 in w.ctrl.suspended                    # 渲染进程被挂起
    assert 2 not in w.ctrl.suspended                # 长任务进程（不可安全处理）不碰
    # 撤销：恢复
    a = next(a for o in outs for a in o.acted if a.kind == "battery_suspend")
    assert eng.undo(a.id)
    assert w.ctrl.suspended == set()


def test_battery_charging_silent(tmp_path):
    w = mk_world(tmp_path, snap=bat_snap(15, True, [renderer(1), busy_proc(2)]))
    reg = Registry(); reg.register(more.battery_prewarn())
    assert step(reg, w, tmp_path) == []


def test_battery_enough_silent(tmp_path):
    w = mk_world(tmp_path, snap=bat_snap(60, False, [renderer(1), busy_proc(2)]))
    reg = Registry(); reg.register(more.battery_prewarn())
    assert step(reg, w, tmp_path) == []


def test_battery_missing_data_silent(tmp_path):
    w = mk_world(tmp_path, snap=SimpleNamespace(procs=[renderer(1)]))
    reg = Registry(); reg.register(more.battery_prewarn())
    assert step(reg, w, tmp_path) == []


def test_battery_recheck_resolves_on_recovery(tmp_path):
    w = mk_world(tmp_path, snap=bat_snap(15, False, [renderer(1), busy_proc(2)]))
    reg = Registry(); reg.register(more.battery_prewarn(threshold=20))
    eng = Engine(reg, tmp_path)
    outs = eng.step(w)
    assert "battery_suspend" in acted_kinds(outs)
    # 电量恢复 -> 问题解除、不再出声
    w.snap.battery = (99, False)
    outs2 = eng.step(w)
    assert outs2 == [] or all(not o.acted for o in outs2)
    assert not eng.open                            # 挂起表已清空


def test_battery_observe_resumes_on_charge(tmp_path):
    w = mk_world(tmp_path, snap=bat_snap(15, False, [renderer(1), busy_proc(2)]))
    reg = Registry(); reg.register(more.battery_prewarn(threshold=20))
    eng = Engine(reg, tmp_path)
    eng.step(w)
    assert 1 in w.ctrl.suspended
    w.snap.battery = (15, True)                    # 开始充电
    eng.step(w)
    assert w.ctrl.suspended == set()               # 状态驱动恢复


# ================================================================ homework_env_prep
def fake_venv_cmd():
    def cmd(dd):
        (Path(dd) / ".venv").mkdir(parents=True, exist_ok=True)
    return cmd


def hw_world(tmp_path, names=("实验1",), user_root=None, templates=None, pre_venv=False, pre_file=None):
    root = user_root or (tmp_path / "Documents")
    root.mkdir(parents=True, exist_ok=True)
    for n in names:
        d = root / n
        d.mkdir(exist_ok=True)
        if pre_venv:
            (d / ".venv").mkdir(exist_ok=True)
        if pre_file:
            (d / pre_file).write_text("用户已有文件", encoding="utf-8")
    if templates is not None:
        tp = tmp_path / "templates"
        tp.mkdir(exist_ok=True)
        (tp / "模板.py").write_text("print('模板')", encoding="utf-8")
    env = Env(now=time.time(), user_dirs=[root])
    if templates:
        env.templates = tmp_path / "templates"    # 场景用 getattr 读，不依赖 Env 声明字段
    return env


def test_homework_prep_creates_venv_and_undo_only_removes_ours(tmp_path):
    env = hw_world(tmp_path, names=("实验1",), templates=True, pre_file="报告.docx")
    w = mk_world(tmp_path, env=env)
    reg = Registry(); reg.register(more.homework_env_prep(venv_cmd=fake_venv_cmd(), install_deps=False, copy_templates=True))
    eng = Engine(reg, tmp_path)
    outs = eng.step(w)
    assert "homework_prep" in acted_kinds(outs)
    d = tmp_path / "Documents" / "实验1"
    assert (d / ".venv").is_dir()                  # venv 建好
    assert (d / ".sprite_prep").exists()           # 标记证明是我们建的
    assert (d / "模板.py").exists()                # 模板复制
    assert (d / "报告.docx").exists()              # 用户文件原样保留
    a = next(a for o in outs for a in o.acted if a.kind == "homework_prep")
    assert eng.undo(a.id)
    assert not (d / ".venv").exists()              # 我们建的：删干净
    assert not (d / ".sprite_prep").exists()
    assert not (d / "模板.py").exists()            # 我们复制的：删掉
    assert (d / "报告.docx").exists()              # 用户自己的：一个不动


def test_homework_prep_skips_existing_venv(tmp_path):
    env = hw_world(tmp_path, names=("作业2",), pre_venv=True)
    w = mk_world(tmp_path, env=env)
    reg = Registry(); reg.register(more.homework_env_prep(venv_cmd=fake_venv_cmd()))
    outs = step(reg, w, tmp_path)
    assert acted_kinds(outs) == []                 # 已有 venv：不动
    assert (tmp_path / "Documents" / "作业2" / ".venv").is_dir()


def test_homework_prep_venv_failure_rolls_back(tmp_path):
    env = hw_world(tmp_path, names=("实验1",))
    w = mk_world(tmp_path, env=env)
    def boom(dd):
        (Path(dd) / ".venv").mkdir(parents=True)  # 建了一半再炸：模拟失败
        raise RuntimeError("venv boom")
    reg = Registry(); reg.register(more.homework_env_prep(venv_cmd=boom))
    eng = Engine(reg, tmp_path)
    outs = eng.step(w)
    assert acted_kinds(outs) == []                 # 失败：不当作成功
    assert outs and any(o.skipped for o in outs)   # 记入 skipped（出错已回滚）
    d = tmp_path / "Documents" / "实验1"
    assert not (d / ".venv").exists()              # 半成品已清掉
    assert not (d / ".sprite_prep").exists()       # 标记没写


def test_homework_prep_no_numbered_dir_silent(tmp_path):
    env = hw_world(tmp_path, names=("项目Alpha",))   # 不是编号作业
    w = mk_world(tmp_path, env=env)
    reg = Registry(); reg.register(more.homework_env_prep(venv_cmd=fake_venv_cmd()))
    assert step(reg, w, tmp_path) == []


def test_homework_prep_does_not_overwrite_user_template(tmp_path):
    env = hw_world(tmp_path, names=("hw3",), templates=True)
    d = tmp_path / "Documents" / "hw3"
    (d / "模板.py").write_text("用户自己的模板，别覆盖", encoding="utf-8")
    w = mk_world(tmp_path, env=env)
    reg = Registry(); reg.register(more.homework_env_prep(venv_cmd=fake_venv_cmd(), copy_templates=True))
    eng = Engine(reg, tmp_path)
    outs = eng.step(w)
    assert "homework_prep" in acted_kinds(outs)
    assert (d / "模板.py").read_text("utf-8") == "用户自己的模板，别覆盖"   # 不覆盖已有文件
    a = next(a for o in outs for a in o.acted if a.kind == "homework_prep")
    assert a.result["copied"] == []               # 复制的清单里没有它（撤销不会误删用户文件）
    eng.undo(a.id)
    assert (d / "模板.py").read_text("utf-8") == "用户自己的模板，别覆盖"


# ================================================================ win_ctrl 真实控制器（假注册表，无头）
class FakeReg:
    """最小 winreg 替身：{(hive, path): {name: (data, type)}}。缺失键/值抛 OSError，与 winreg 一致。"""
    KEY_READ = 0x20019; KEY_WRITE = 0x20006; KEY_SET_VALUE = 0x0002
    REG_DWORD = 4
    HKEY_CURRENT_USER = 0x80000001; HKEY_LOCAL_MACHINE = 0x80000002

    def __init__(self, hkcu_run=None, hklm_run=None):
        self.data = {}
        if hkcu_run: self.data[(self.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")] = dict(hkcu_run)
        if hklm_run: self.data[(self.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")] = dict(hklm_run)

    def OpenKey(self, hive, path, res=0, access=0):
        k = (hive, path)
        if k not in self.data: raise OSError("missing key")
        return {"hive": hive, "path": path, "k": k}

    def CreateKeyEx(self, hive, path, res=0, access=0):
        k = (hive, path); self.data.setdefault(k, {}); return {"hive": hive, "path": path, "k": k}

    def EnumValue(self, key, i):
        vals = list(self.data.get(key["k"], {}).items())
        if i >= len(vals): raise OSError("no more")
        name, (data, typ) = vals[i]
        return name, data, typ

    def QueryValueEx(self, key, name):
        d = self.data.get(key["k"], {})
        if name not in d: raise OSError("no value")
        return d[name]

    def SetValueEx(self, key, name, res, typ, data):
        self.data[key["k"]][name] = (data, typ)

    def DeleteValue(self, key, name):
        d = self.data.get(key["k"], {})
        if name not in d: raise OSError("no value")
        del d[name]

    def CloseKey(self, key):
        pass


def mk_ctrl(tmp_path, reg=None, startup_folder=None):
    sf = Path(tmp_path) / "startup"
    if startup_folder:
        sf.mkdir(exist_ok=True)
        for n in startup_folder:
            (sf / n).write_bytes(b"X")
    return WindowsController(home=Path(tmp_path) / "home", reg=reg, startup_folder=sf if startup_folder else None)


def test_startup_disable_backs_up_then_restores(tmp_path):
    reg = FakeReg(hkcu_run={"Junk1": ("\"C:\\Junk1.exe\"", 1)})
    c = mk_ctrl(tmp_path, reg=reg)
    assert c.startup_disable("Junk1")
    assert reg.data[(FakeReg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")] == {}   # 值已删
    bak = json.loads((Path(tmp_path) / "home" / "win_ctrl_backup.json").read_text("utf-8"))
    assert bak["startup"]["Junk1"]["hive"] == "HKCU" and bak["startup"]["Junk1"]["data"] == "\"C:\\Junk1.exe\""
    assert c.startup["Junk1"] is False
    assert c.startup_enable("Junk1")
    assert reg.data[(FakeReg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")]["Junk1"] == ("\"C:\\Junk1.exe\"", 1)
    assert c.startup["Junk1"] is True


def test_startup_folder_moves_file_and_restores(tmp_path):
    c = mk_ctrl(tmp_path, reg=None, startup_folder=["Junk2.lnk"])
    sf = Path(tmp_path) / "startup"
    assert c.startup_disable("Junk2")
    assert not (sf / "Junk2.lnk").exists()
    assert (Path(tmp_path) / "home" / "startup_disabled" / "Junk2.lnk").exists()
    assert c.startup_enable("Junk2")
    assert (sf / "Junk2.lnk").exists()


def test_mute_unmute_restores_original(tmp_path):
    reg = FakeReg()
    c = mk_ctrl(tmp_path, reg=reg)
    key = (FakeReg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\PromoApp")
    # 原来 Enabled=1：静音后应改成 0，撤销后还原 1
    reg.data[key] = {"Enabled": (1, FakeReg.REG_DWORD)}
    assert c.mute("PromoApp")
    assert reg.data[key]["Enabled"][0] == 0
    assert "PromoApp" in c.muted
    assert c.unmute("PromoApp")
    assert reg.data[key]["Enabled"][0] == 1
    assert "PromoApp" not in c.muted
    # 没有原值：静音后撤销应删掉 Enabled，回到系统默认
    c.mute("NewApp")
    assert reg.data[(FakeReg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\NewApp")]["Enabled"][0] == 0
    c.unmute("NewApp")
    assert "Enabled" not in reg.data[(FakeReg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\NewApp")]


def test_unknown_name_no_crash(tmp_path):
    reg = FakeReg(hkcu_run={"Keep1": ("x", 1)})
    c = mk_ctrl(tmp_path, reg=reg)
    assert c.startup_disable("Nope") is False      # 找不到：宁可漏做
    assert c.startup_enable("Nope") is True        # 备份里没有：视为已恢复（无操作）
    assert c.mute("Whatever") is True


def test_no_registry_safe_noop(tmp_path):
    c = mk_ctrl(tmp_path, reg=None)
    assert c.mute("AppX") is True
    assert c.unmute("AppX") is True
    assert c.startup_disable("Nope") is False
    assert ("mute", "AppX") in c.calls             # 操作轨迹仍记录（审计可见）


def test_composite_merges_process_and_win_ctrl(tmp_path):
    fc = FakeController()
    wc_ = WindowsController(home=Path(tmp_path) / "home", reg=None)
    c = Composite(wc_, fc)                        # 自启/通知走真实控制器，进程走 FakeController
    assert c.suspend(9) is True and 9 in c.suspended
    assert c.mute("AppY") is True and "AppY" in c.muted
    assert c.startup_disable("Nope") is False     # 真实控制器找不到项：宁可漏做
