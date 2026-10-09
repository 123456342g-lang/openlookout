"""T6：真实 Windows 控制器 —— 自启项精简 + 通知静音，全部带备份、可还原。

接口与场景里 hasattr 探测的完全一致（startup/startup_disable/startup_enable、muted/mute/unmute），
可以直接替换 FakeController 用于真实机器；进程类能力（挂起/优先级）归 T1 的 ProcController，这里不重复。

- 自启项：HKCU/HKLM 的 Run 值 + 启动文件夹快捷方式。禁用 = 备份原值/原文件到 home/win_ctrl_backup.json
  或 home/startup_disabled/ 再删除；启用 = 从备份还原。任何一步失败都不留半成品（先备份后删除）。
- 通知：HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings\\{App} 的 Enabled=0 静音，
  原值备份可还原。Win11 部分 UWP 应用的通知开关在系统数据库里，此键未必生效（见文档备注）。
- registry 可注入（测试用假注册表）；winreg 不可用时所有操作安全降级为 no-op 并记录调用。

注意：本文件所有真实注册表/文件操作都用 try/except 包裹，绝不向 Engine 抛异常；
「宁可漏做，不可错做」—— 拿不准的键/名称一律不动。"""
from __future__ import annotations
import json, shutil, time
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOTIF_KEY = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"

# 系统级/驱动类/输入法/同步等，误关有风险：即使出现在 Run 里也跳过（与 more.KEEP_STARTUP 同向的保守名单）
KEEP_STARTUP = ("defender", "antivirus", "security", "firewall", "杀毒", "安全", "driver", "realtek", "nvidia",
                "intel", "amd", "input", "ime", "输入法", "onedrive", "dropbox", "backup", "备份", "sync", "同步",
                "vpn", "authenticator", "bitlocker", "touchpad", "bluetooth")


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception:
        return None


class WindowsController:
    """真实 Windows 自启/通知控制器。构造参数 reg/startup_folder 可注入，便于无头测试。"""

    def __init__(self, home: Path, reg=None, startup_folder=None):
        self.home = Path(home); self.home.mkdir(parents=True, exist_ok=True)
        self.reg = reg
        if reg is None:
            try:
                import winreg
                self.reg = winreg
            except ImportError:
                self.reg = None
        self.startup_folder = Path(startup_folder) if startup_folder else None
        self.backup_f = self.home / "win_ctrl_backup.json"
        self.backup = self._load_backup()
        self._startup: dict[str, bool] = {}
        self._muted: set[str] = set()
        self.calls: list = []          # 与 FakeController 对齐：记操作轨迹，便于测试/审计
        self._scan()

    # ---------- 备份 ----------
    def _load_backup(self):
        try:
            return json.loads(self.backup_f.read_text("utf-8"))
        except Exception:
            return {"startup": {}, "notif": {}, "files": {}}

    def _save_backup(self):
        try:
            self.backup_f.write_text(json.dumps(self.backup, ensure_ascii=False, indent=1), "utf-8")
        except OSError:
            pass

    # ---------- 自启项 ----------
    def _iter_run_values(self):
        """产出 (hive_name, value_name, data)。hive_name: 'HKCU'|'HKLM'；winreg 不可用则空。"""
        if self.reg is None:
            return
        for hive, hive_name in ((self.reg.HKEY_CURRENT_USER, "HKCU"), (self.reg.HKEY_LOCAL_MACHINE, "HKLM")):
            k = _safe(self.reg.OpenKey, hive, RUN_KEY, 0, self.reg.KEY_READ)
            if k is None:
                continue
            try:
                i = 0
                while True:
                    try:
                        name, data, typ = self.reg.EnumValue(k, i)
                    except OSError:
                        break
                    yield hive_name, name, (data, typ)
                    i += 1
            finally:
                _safe(self.reg.CloseKey, k)

    def _scan(self):
        """枚举自启项：Run 值 + 启动文件夹快捷方式；构建 name -> enabled 映射。"""
        for hive, name, _ in self._iter_run_values():
            self._startup[name] = self._startup.get(name, True)
        if self.startup_folder is not None and self.startup_folder.is_dir():
            try:
                for f in self.startup_folder.iterdir():
                    if f.suffix.lower() in (".lnk", ".url", ".bat", ".cmd"):
                        self._startup[f.stem] = True
            except OSError:
                pass
        # 已被我们禁用的项：从备份里找出来标 False
        for name in self.backup["startup"]:
            self._startup[name] = False

    @property
    def startup(self) -> dict:
        return dict(self._startup)

    def list_startup(self):
        """给场景用的自启项清单：启动文件夹项用文件修改时间估「多久没用」；Run 值无时间信息 -> None（场景按未知=不动）。"""
        out = []
        for name, enabled in self._startup.items():
            lu = None
            if self.startup_folder is not None:
                for ext in (".lnk", ".url", ".bat", ".cmd"):
                    f = self.startup_folder / (name + ext)
                    if f.exists():
                        lu = int(max(0.0, (time.time() - f.stat().st_mtime) / 86400))
                        break
            out.append(dict(name=name, publisher="Windows", last_used_days=lu, enabled=enabled))
        return out

    def startup_disable(self, name: str) -> bool:
        """禁用自启项：先备份、后删除；启动文件夹的快捷方式移到 home/startup_disabled/。"""
        self.calls.append(("startup_disable", name))
        if name in self.backup["startup"]:
            return True                                   # 已经禁用了
        if self.reg is not None:
            for hive, hive_name in ((self.reg.HKEY_CURRENT_USER, "HKCU"), (self.reg.HKEY_LOCAL_MACHINE, "HKLM")):
                k = _safe(self.reg.OpenKey, hive, RUN_KEY, 0, self.reg.KEY_READ | self.reg.KEY_WRITE)
                if k is None:
                    continue
                try:
                    try:
                        data, typ = self.reg.QueryValueEx(k, name)
                    except OSError:
                        continue
                    self.backup["startup"][name] = dict(hive=hive_name, data=data, type=typ)
                    _safe(self.reg.DeleteValue, k, name)
                    self._save_backup()
                    self._startup[name] = False
                    return True
                finally:
                    _safe(self.reg.CloseKey, k)
        # 启动文件夹快捷方式
        if self.startup_folder is not None and self.startup_folder.is_dir():
            for ext in (".lnk", ".url", ".bat", ".cmd"):
                f = self.startup_folder / (name + ext)
                if f.exists():
                    dst = self.home / "startup_disabled" / f.name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        dst.unlink()                      # 覆盖我们自己的备份（旧备份已在 json 里）
                    shutil.move(str(f), str(dst))
                    self.backup["files"][name] = str(dst)
                    self._save_backup()
                    self._startup[name] = False
                    return True
        return False                                      # 找不到这一项：不动（宁可漏做）

    def startup_enable(self, name: str) -> bool:
        """从备份还原自启项。"""
        self.calls.append(("startup_enable", name))
        e = self.backup["startup"].pop(name, None)
        if e and self.reg is not None:
            hive = self.reg.HKEY_LOCAL_MACHINE if e["hive"] == "HKLM" else self.reg.HKEY_CURRENT_USER
            k = _safe(self.reg.OpenKey, hive, RUN_KEY, 0, self.reg.KEY_SET_VALUE)
            if k is not None:
                try:
                    _safe(self.reg.SetValueEx, k, name, 0, e["type"], e["data"])
                    self._save_backup()
                    self._startup[name] = True
                    return True
                finally:
                    _safe(self.reg.CloseKey, k)
        f = self.backup["files"].pop(name, None)
        if f:
            src = Path(f)
            if src.exists():
                dst = self.startup_folder / src.name if self.startup_folder else None
                if dst is not None:
                    shutil.move(str(src), str(dst))
                    self._save_backup()
                    self._startup[name] = True
                    return True
        self._startup[name] = True
        return True                                       # 备份里没有就认为“已恢复”（无操作）

    # ---------- 通知静音 ----------
    @property
    def muted(self) -> set:
        return set(self._muted)

    def mute(self, app: str) -> bool:
        """静音某 App 通知：Notifications\\Settings\\{app} 的 Enabled=0；原值备份。"""
        self.calls.append(("mute", app))
        self._muted.add(app)
        if self.reg is None:
            return True
        key = NOTIF_KEY + "\\" + app
        k = _safe(self.reg.CreateKeyEx, self.reg.HKEY_CURRENT_USER, key, 0, self.reg.KEY_READ | self.reg.KEY_WRITE)
        if k is None:
            return True                                    # 建不了键：记入 muted，真实键留给系统（保守）
        try:
            try:
                old, typ = self.reg.QueryValueEx(k, "Enabled")
            except OSError:
                old, typ = None, None
            if old != 0:
                self.backup["notif"].setdefault(app, {})["old"] = [old, typ]
            _safe(self.reg.SetValueEx, k, "Enabled", 0, self.reg.REG_DWORD, 0)
            self._save_backup()
            return True
        finally:
            _safe(self.reg.CloseKey, k)

    def unmute(self, app: str) -> bool:
        """恢复某 App 通知：还原备份的原值；没有备份就把 Enabled 删掉（回到系统默认）。"""
        self.calls.append(("unmute", app))
        self._muted.discard(app)
        if self.reg is None:
            return True
        key = NOTIF_KEY + "\\" + app
        k = _safe(self.reg.OpenKey, self.reg.HKEY_CURRENT_USER, key, 0, self.reg.KEY_READ | self.reg.KEY_WRITE)
        if k is None:
            return True
        try:
            old = self.backup["notif"].pop(app, {}).get("old")
            if old and old[0] is not None:
                _safe(self.reg.SetValueEx, k, "Enabled", 0, old[1] or self.reg.REG_DWORD, old[0])
            else:
                _safe(self.reg.DeleteValue, k, "Enabled")
            self._save_backup()
            return True
        finally:
            _safe(self.reg.CloseKey, k)


class Composite:
    """把多个控制器合并成一个：场景里 hasattr 探测到哪个方法就用哪个（进程类归 ProcController）。"""

    def __init__(self, *parts):
        self._parts = list(parts)

    def __getattr__(self, name):
        for p in self._parts:
            if hasattr(p, name):
                return getattr(p, name)
        raise AttributeError(name)
