"""“烦人的东西”插件包：只通过 investigate.InvestigatorRegistry 注册，核心零改动。
发现器：
  console_popups  反复出现的可见黑色命令行窗口（按计划任务/启动源归因）
  dup_process     同一程序有多个实例，老的疑似陈旧
  orphan_process  父进程已不在的长期后台脚本/解释器进程
裁判/响应器：
  task_popup -> 把任务动作包成 conhost --headless（行为不变、不再有窗口；先把原任务 XML 整份存档；可原样还原；事后真跑一次校验）
  process    -> 挂起（不杀；写日志，退出时自动恢复；可撤销）
所有判断来自证据（启动时间、有没有更新的同类在跑、有没有人依赖、项目最近有没有人改/开发会话在跑），不按名字硬编码。"""
from __future__ import annotations
import json, os, re, shutil, subprocess, threading, time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from ..framework import Action
from ..investigate import (Candidate, Understanding, InvestigatorRegistry, Investigator, RealSysView, register_generic, program_sig, family_sig,
                           investigator_scenario, default_judge, NO_WINDOW, _is_desc)

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
CONSOLE_STEMS = {"powershell", "pwsh", "cmd", "python", "node", "bash", "wsl", "java", "ruby", "perl", "go", "cargo", "npm", "npx", "git", "curl"}
SCRIPT_EXT = {".ps1", ".mjs", ".js", ".cjs", ".py", ".bat", ".cmd", ".vbs", ".sh"}
SEC_VENDOR_RE = re.compile(r"defender|antivir|kaspersky|norton|mcafee|avast|bitdefender|eset|huorong|360|security|nvidia|\bnv[a-z]|geforce|realtek|rtk|intel|amd|driver|bluetooth|windows|microsoft|edgeupdate", re.I)
SYSTEM_DIRS = ("c:\\windows", "c:\\program files", "c:\\programdata")
INTERACTIVE_RE = re.compile(r"Read-Host|\bpause\b|ReadKey|\binput\(|\bgetpass|readline|Out-GridView|\$Host\.UI\.PromptForChoice", re.I)
PER_FLASH_S = 3.0


def stem(x: str) -> str: return Path(str(x).strip('"')).stem.lower()
def tokens(s: str) -> list: return [t.strip('"') for t in re.findall(r'"[^"]*"|\S+', s or "")]


def is_console_exe(cmd: str) -> bool:
    s = stem(cmd)
    if s in CONSOLE_STEMS or s == "conhost": return True
    p = shutil.which(cmd) or cmd
    try:
        with open(p, "rb") as f:
            h = f.read(4096)
        pe = int.from_bytes(h[0x3c:0x40], "little"); return int.from_bytes(h[pe + 92:pe + 94], "little") == 3
    except Exception: return False


# ---------------- 计划任务后端 ----------------
@dataclass
class TaskInfo:
    path: str                  # 如 \CVEArchWatchdog
    xml: str
    last_run: float = 0.0
    last_result: int = 0
    state: str = "Ready"

    @property
    def name(self): return self.path.rsplit("\\", 1)[-1]


def parse_task(xml: str) -> dict:
    x = re.sub(r"^<\?xml[^>]*\?>", "", xml.strip()); r = ET.fromstring(x); q = lambda t: r.findall(f".//{{{NS}}}{t}")
    ex = q("Exec"); g = lambda e, t: (e.findtext(f"{{{NS}}}{t}") or "") if e is not None else ""
    iv = r.findtext(f".//{{{NS}}}Repetition/{{{NS}}}Interval") or ""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iv); secs = None
    if m: d, h, mi, s = (int(v or 0) for v in m.groups()); secs = d * 86400 + h * 3600 + mi * 60 + s or None
    return dict(command=g(ex[0], "Command") if ex else "", args=g(ex[0], "Arguments") if ex else "", wd=g(ex[0], "WorkingDirectory") if ex else "", n_exec=len(ex),
                desc=r.findtext(f".//{{{NS}}}RegistrationInfo/{{{NS}}}Description") or "", author=r.findtext(f".//{{{NS}}}RegistrationInfo/{{{NS}}}Author") or "",
                logon=r.findtext(f".//{{{NS}}}Principal/{{{NS}}}LogonType") or "", interval_s=secs, enabled=(r.findtext(f".//{{{NS}}}Settings/{{{NS}}}Enabled") or "true").lower() != "false")


def windowless(command: str, args: str) -> bool:
    return (stem(command) == "conhost" and "--headless" in args.lower()) or not is_console_exe(command)


def make_headless(xml: str, conhost: str) -> str:
    decl = re.match(r"^<\?xml[^>]*\?>", xml.strip()); ET.register_namespace("", NS)
    r = ET.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", xml.strip())); e = r.find(f".//{{{NS}}}Exec")
    cmd = e.find(f"{{{NS}}}Command"); a = e.find(f"{{{NS}}}Arguments")
    old_cmd = cmd.text.strip(); old_args = (a.text or "") if a is not None else ""
    if a is None: a = ET.SubElement(e, f"{{{NS}}}Arguments"); cmd_idx = list(e).index(cmd); e.remove(a); e.insert(cmd_idx + 1, a)
    cmd.text = conhost; a.text = f'--headless {chr(34) + old_cmd + chr(34) if " " in old_cmd else old_cmd} {old_args}'.rstrip()
    return (decl.group(0) if decl else '<?xml version="1.0" encoding="UTF-16"?>') + "\n" + ET.tostring(r, encoding="unicode")


class RealTaskBackend:
    def __init__(self, home: Path): self.home = Path(home); self.home.mkdir(parents=True, exist_ok=True); self.n = 0
    def _ps(self, body: str, timeout=60):
        self.n += 1; f = self.home / f"_ps_{os.getpid()}_{self.n}.ps1"
        f.write_text(body, encoding="utf-8-sig")
        try: return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(f)], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        finally: f.unlink(missing_ok=True)
    def list_tasks(self) -> list:
        out = self.home / "_tasks.json"; out.unlink(missing_ok=True)
        self._ps(r'''$ErrorActionPreference="SilentlyContinue"
$r=@(Get-ScheduledTask | ? {$_.TaskPath -notlike '\Microsoft*'} | ForEach-Object {
 $i=Get-ScheduledTaskInfo -TaskName $_.TaskName -TaskPath $_.TaskPath
 [pscustomobject]@{path=($_.TaskPath+$_.TaskName); xml=[string](Export-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath | Out-String); last=$(if($i.LastRunTime){$i.LastRunTime.ToUniversalTime().ToString('o')}else{''}); res=[int64]$i.LastTaskResult; state=[string]$_.State}})
$r | ConvertTo-Json -Compress -Depth 3 | Set-Content -Encoding UTF8 -LiteralPath "%s"''' % str(out))
        if not out.exists(): return []
        d = json.loads(out.read_text("utf-8-sig") or "[]"); d = d if isinstance(d, list) else [d]; out.unlink(missing_ok=True); res = []
        for t in d:
            try:
                import datetime
                lr = datetime.datetime.fromisoformat(t["last"].replace("Z", "+00:00")).timestamp() if t["last"] and not t["last"].startswith("1999") else 0.0
            except Exception: lr = 0.0
            res.append(TaskInfo(t["path"], t["xml"].strip(), lr, int(t["res"]), t["state"]))
        return res
    def register(self, path: str, xml: str):
        d, n = path.rsplit("\\", 1); f = self.home / f"_reg_{os.getpid()}.xml"; f.write_text(xml, encoding="utf-16")
        try:
            folder = (d + "\\") if d else "\\"
            r = self._ps(r'''$ErrorActionPreference="Stop"
$x=Get-Content -Raw -Encoding Unicode -LiteralPath "%s"
Register-ScheduledTask -Xml $x -TaskName "%s" -TaskPath "%s" -Force | Out-Null''' % (f, n, folder))
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or b"").decode("utf-8", "replace")[:400]
                raise RuntimeError(msg or f"register failed rc={r.returncode}")
        finally:
            f.unlink(missing_ok=True)

    def start(self, path: str):
        d, n = path.rsplit("\\", 1); self._ps(r'Start-ScheduledTask -TaskName "%s" -TaskPath "%s"' % (n, (d + "\\") if d else "\\"), 30)
    def info(self, path: str) -> TaskInfo | None:
        d, n = path.rsplit("\\", 1); out = self.home / "_info.json"; out.unlink(missing_ok=True)
        self._ps(r'''$ErrorActionPreference="SilentlyContinue"
$t=Get-ScheduledTask -TaskName "%s" -TaskPath "%s"; $i=Get-ScheduledTaskInfo -TaskName "%s" -TaskPath "%s"
if($t){[pscustomobject]@{path="%s"; xml=[string](Export-ScheduledTask -TaskName "%s" -TaskPath "%s" | Out-String); last=$(if($i.LastRunTime){$i.LastRunTime.ToUniversalTime().ToString('o')}else{''}); res=[int64]$i.LastTaskResult; state=[string]$t.State} | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 -LiteralPath "%s"}''' % (n, (d + "\\") if d else "\\", n, (d + "\\") if d else "\\", path, n, (d + "\\") if d else "\\", out), 40)
        if not out.exists(): return None
        import datetime
        t = json.loads(out.read_text("utf-8-sig")); out.unlink(missing_ok=True)
        try: lr = datetime.datetime.fromisoformat(t["last"].replace("Z", "+00:00")).timestamp() if t["last"] and not t["last"].startswith("1999") else 0.0
        except Exception: lr = 0.0
        return TaskInfo(t["path"], t["xml"].strip(), lr, int(t["res"]), t["state"])


# ---------------- 命令行窗口观察器 ----------------
@dataclass
class Launch:
    ts: float; pid: int; ppid: int; cmd: list
    visible: bool = False; headless: bool = False; parent: str = ""

    def d(self): return dict(ts=self.ts, pid=self.pid, ppid=self.ppid, cmd=self.cmd, visible=self.visible, headless=self.headless, parent=self.parent)


class ConsoleObserver:
    """后台采样线程：给新出现的控制台程序登记“有没有可见窗口”（状态观察，不是定时触发；0.25s 间隔只 diff 进程号）。"""
    def __init__(self, home: Path, keep_s=14400.0, clock=time.time):
        self.home, self.keep_s, self.clock = Path(home), keep_s, clock; self.items: list[Launch] = []; self.lock = threading.Lock(); self.t = None
        self.file = self.home / "console_launches.jsonl"
        try:
            for l in self.file.read_text("utf-8").splitlines()[-3000:]:
                d = json.loads(l)
                if clock() - d["ts"] < keep_s: self.items.append(Launch(**d))
        except Exception: pass
    def start(self):
        if self.t and self.t.is_alive(): return
        self.t = threading.Thread(target=self._run, daemon=True); self.t.start()
    def launches(self, since: float) -> list:
        with self.lock: return [l for l in self.items if l.ts >= since]
    def add(self, l: Launch):
        with self.lock: self.items.append(l)
        try:
            with self.file.open("a", encoding="utf-8") as f: f.write(json.dumps(l.d(), ensure_ascii=False) + "\n")
        except Exception: pass
    def _visible_owner_pids(self) -> set:
        if os.name != "nt": return set()
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32; res = set(); buf = ctypes.create_unicode_buffer(256)
        def cb(h, _):
            if u.IsWindowVisible(h):
                u.GetClassNameW(h, buf, 256)
                if buf.value in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
                    p = wintypes.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(p)); res.add(p.value)
            return True
        u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0); return res
    def _run(self):
        import psutil
        known = set(psutil.pids()); pending: dict = {}
        while True:
            time.sleep(0.25)
            try:
                cur = set(psutil.pids()); new = cur - known; known = cur
                for pid in new:
                    try:
                        p = psutil.Process(pid); cmd = p.cmdline() or []; nm = (p.name() or "").lower()
                        if not cmd or not (is_console_exe(cmd[0]) or nm == "conhost.exe"): continue
                        if stem(nm) == "conhost" and "--headless" not in " ".join(cmd).lower(): continue
                        par = p.parent(); pcmd = " ".join(par.cmdline()).lower() if par else ""
                        pending[pid] = dict(t0=self.clock(), cmd=cmd, ppid=p.ppid(), parent=(par.name() if par else ""), headless=("--headless" in " ".join(cmd).lower() or "--headless" in pcmd))
                    except Exception: continue
                if pending:
                    vis = self._visible_owner_pids()
                    for pid in list(pending):
                        d = pending[pid]; v = False; alive = True
                        try:
                            pr = psutil.Process(pid); kids = [k for k in pr.children() if k.name().lower() in ("conhost.exe", "openconsole.exe")]
                            v = (pid in vis or any(k.pid in vis for k in kids)) and not d["headless"]
                            if not v and not d["headless"] and re.search(r"-w(indowstyle)?\s+hidden", " ".join(d["cmd"]), re.I) and any("--headless" not in " ".join(k.cmdline()).lower() for k in kids): v = True   # -WindowStyle Hidden 仍会先闪一下
                        except Exception: alive = False
                        if v or not alive or self.clock() - d["t0"] > 1.5:
                            self.add(Launch(d["t0"], pid, d["ppid"], d["cmd"], v, d["headless"], d["parent"])); pending.pop(pid)
            except Exception: pass
    def visible_since(self, ts: float, match) -> int: return sum(1 for l in self.launches(ts) if l.visible and match(l.cmd))


def _norm_cmd(c: list) -> list:
    c = [t.strip('"') for t in c]
    if c and stem(c[0]) == "conhost":
        c = c[1:]
        if c and c[0].lower() == "--headless": c = c[1:]
    return c


def action_match(command: str, args: str):
    """某条任务动作 -> 判断一次启动命令行是否来自它（包过 conhost --headless 也认，前后一致）。"""
    want = _norm_cmd([command] + tokens(args)); wl = [t.lower() for t in want[1:]]; ws = stem(want[0]) if want else ""
    def m(cmd: list) -> bool:
        c = _norm_cmd(cmd)
        return bool(c) and stem(c[0]) == ws and [t.lower() for t in c[1:]] == wl
    return m

# ---------------- 1) 反复出现的黑窗 ----------------
class PopupKit:
    def __init__(self, backend, observer, view, home: Path, clock=time.time, window_s=3600.0, min_hits=3, conhost=None, task_ttl=30.0, sleep=time.sleep):
        self.b, self.obs, self.view, self.home, self.clock, self.sleep = backend, observer, view, Path(home), clock, sleep
        self.window_s, self.min_hits = window_s, min_hits; self.conhost = conhost or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "conhost.exe")
        self._tasks = ([], 0.0); self.task_ttl = task_ttl; self.changed: dict[str, float] = {}; self.jdir = self.home / "inv_journal"; self.jdir.mkdir(parents=True, exist_ok=True)
        try:
            for l in (self.jdir / 'index.jsonl').read_text('utf-8').splitlines():
                d = json.loads(l); self.changed[d['path']] = max(self.changed.get(d['path'], 0), d['ts'])
        except Exception: pass
    def tasks(self, fresh=False) -> list:
        t, ts = self._tasks
        if fresh or self.clock() - ts > self.task_ttl: t = self.b.list_tasks(); self._tasks = (t, self.clock())
        return t
    def task(self, path, fresh=False): return next((t for t in self.tasks(fresh) if t.path == path), None)
    def discover(self, w) -> list:
        """两类通用信号：①已观察到的可见黑窗复发；②计划任务定义本身就是周期性拉起控制台且未无窗化（闪得太快抓不到窗也能立项）。"""
        self.obs.start(); now = self.clock(); L = [l for l in self.obs.launches(now - self.window_s) if l.visible]
        tasks = self.tasks(); groups: dict = {}; rest: dict = {}; out = []; seen = set()
        for l in L:
            hit = None
            for t in tasks:
                pi = parse_task(t.xml)
                if pi["n_exec"] == 1 and action_match(pi["command"], pi["args"])(l.cmd): hit = t; break
            if hit: groups.setdefault(hit.path, []).append(l)
            else: rest.setdefault((stem(l.cmd[0]), l.parent), []).append(l)
        for path, ls in groups.items():
            if len(ls) < self.min_hits: continue
            t = self.task(path); pi = parse_task(t.xml)
            if windowless(pi["command"], pi["args"]) and not any(l.ts > self.changed.get(path, 0) for l in ls): continue
            n = len(ls); perh = n / (self.window_s / 3600); seen.add(path)
            out.append(Candidate("task_popup", f"task:{path}", f"计划任务 {path} 反复弹黑窗", dict(recurrence=n, visible=True, per_hour=round(perh, 1), cost_s=n * PER_FLASH_S, severity=min(1.0, 0.2 + perh * PER_FLASH_S / 120), need=float(n), unit="次"), dict(path=path)))
        for (nm, par), ls in rest.items():
            if len(ls) >= self.min_hits: out.append(Candidate("popup_launcher", f"launcher:{nm}:{par}", f"{par or '未知启动者'} 反复拉起可见的 {nm} 窗口", dict(recurrence=len(ls), visible=True, severity=0.3, need=float(len(ls)), unit="次"), dict(sample=" ".join(ls[-1].cmd)[:200])))
        for t in tasks:
            if t.path in seen: continue
            pi = parse_task(t.xml)
            if pi.get("n_exec") != 1: continue
            if windowless(pi["command"], pi["args"]): continue
            if not is_console_exe(pi["command"]): continue
            interval = float(pi.get("interval_s") or 0)
            if interval <= 0 or interval > 3600: continue
            if t.last_run and (now - t.last_run) > max(interval * 3, 1800): continue
            perh = 3600.0 / interval; n = max(3, int(perh))
            out.append(Candidate("task_popup", f"task:{t.path}", f"计划任务 {t.path} 周期性拉起控制台（易弹黑窗）", dict(recurrence=n, visible=False, per_hour=round(perh, 1), cost_s=n * PER_FLASH_S, severity=min(1.0, 0.25 + perh * PER_FLASH_S / 120), need=float(n), unit="次", from_definition=True), dict(path=t.path)))
        return out

    def g_task(self, c, facts, world, view) -> list:
        t = self.task(c.ctx["path"]); pi = parse_task(t.xml); facts["task"] = pi; ev = []
        cmd = pi["command"]; script = next((x for x in tokens(pi["args"]) + [cmd] if Path(x).suffix.lower() in SCRIPT_EXT and view.exists(x)), None)
        head = view.read_head(script) if script else ""; facts["script"] = script
        every = f"每 {pi['interval_s']/60:.0f} 分钟" if pi["interval_s"] else "按触发器"
        ev.append(f"任务动作：{cmd} {pi['args'][:120]}；{every}触发；最近运行 {time.strftime('%m-%d %H:%M', time.localtime(t.last_run)) if t.last_run else '未知'}，结果 {t.last_result}")
        lines = [l.strip(" #/*") for l in head.splitlines()[:12] if l.strip().startswith(("#", "//", "/*", "*", "REM", "::"))]
        facts["what"] = (pi["desc"] or " ".join(lines[:2]) or f"运行 {script or cmd}")[:160]
        ev.append(f"它是什么：{facts['what']}")
        where = (script or pi["wd"] or "").lower(); u_own = bool(where) and not where.startswith(SYSTEM_DIRS) and "\\appdata\\local\\programs" not in where
        facts["owner"] = "你自己的脚本/项目" if u_own else "第三方/系统"; ev.append(f"归属：{facts['owner']}（{script or '无脚本'}）")
        if t.path.lower().startswith("\\microsoft") or SEC_VENDOR_RE.search(t.path + " " + pi["command"] + " " + pi["author"] + " " + (script or "")): facts["protected"] = "系统/安全/驱动类任务，不碰"
        elif not u_own: facts["vendor"] = True
        if INTERACTIVE_RE.search(head): facts["interactive"] = True; ev.append("脚本里有读取输入/交互的写法：藏起窗口会破坏它")
        else: ev.append("藏起窗口的代价：无（脚本不需要键盘输入，输出本来也没人看）")
        if pi["n_exec"] != 1: facts["protected"] = "任务有多个动作，改不安全"
        if script:
            root = view.git_root(str(Path(script).parent)) or str(Path(script).parent); m = view.newest_mtime(root, depth=2, cap=2000)
            if m: facts["dev_recent_s"] = view.now() - m; ev.append(f"脚本所在项目 {root} 最近改动 {facts['dev_recent_s']/3600:.1f} 小时前（{'开发中' if facts['dev_recent_s'] < 86400 else '稳定'}）")
        return ev
    def judge(self, c, facts) -> Understanding:
        u = Understanding(c.key, c.kind, c.title, what=facts.get("what", ""), owner=facts.get("owner", ""))
        if facts.get("protected"): u.state, u.confidence, u.why = "protected", 1.0, facts["protected"]
        elif facts.get("vendor"): u.state, u.confidence, u.why = "vendor", 0.9, "不是你自己的脚本（厂商/第三方），不改"
        elif facts.get("interactive"): u.state, u.confidence, u.why = "in_use", 0.9, "需要交互，藏窗口会破坏"
        else:
            u.state = "under_development" if facts.get("dev_recent_s", 1e9) < 86400 else "in_use"; u.confidence = 0.85; u.act = True
            u.why = f"这是你自己的定时任务（{u.what[:40]}），窗口只是副作用；包成无窗口启动，行为不变，原任务整份存档可还原"
        return u
    def recheck(self, c, w) -> float:
        """未无窗化=问题仍在；已无窗化则看是否还有可见闪窗残留。"""
        path = c.ctx["path"]; t = self.task(path)
        if not t: return 0.0
        pi = parse_task(t.xml); now = self.clock(); m = action_match(pi["command"], pi["args"])
        if not windowless(pi["command"], pi["args"]):
            return float(c.signals.get("need", 1.0))   # 定义上仍会弹：未解除
        since = max(now - self.window_s, self.changed.get(path, 0.0))
        return float(self.obs.visible_since(since, m))
    def propose(self, c, u, w) -> list:
        path = c.ctx["path"]; kit = self; n = int(c.signals["recurrence"])
        def dry():
            t = kit.task(path, fresh=True); return bool(t) and not windowless(*[parse_task(t.xml)[k] for k in ("command", "args")]) and parse_task(t.xml)["n_exec"] == 1
        def run():
            t = kit.task(path, fresh=True); orig = t.xml; j = kit.jdir / (re.sub(r"[^\w.-]+", "_", path) + f"_{int(kit.clock())}.xml"); j.write_text(orig, encoding="utf-16")
            new = make_headless(orig, kit.conhost); kit.b.register(path, new); kit.changed[path] = kit.clock()
            (kit.jdir / "index.jsonl").open("a", encoding="utf-8").write(json.dumps(dict(path=path, backup=str(j), ts=kit.clock())) + "\n")
            return dict(path=path, backup=str(j), t0=kit.clock(), before=dict(result=t.last_result, last=t.last_run))
        def verify(r):
            before = kit.task(path, fresh=True)
            if kit.b.info(path) is None: return False
            kit.b.start(path); t_end = kit.clock() + 25; seen = False
            while kit.clock() < t_end:
                kit.sleep(1.0); t = kit.b.info(path)
                if t and t.last_run >= r["t0"] - 1: seen = True
                if seen and t and t.state != "Running": break
            t = kit.b.info(path)
            if not t or not seen and t.state != "Running": return False
            if kit.obs.visible_since(r["t0"], action_match(*[parse_task(t.xml)[k] for k in ("command", "args")])) > 0: return False
            return t.last_result in (0, r["before"]["result"]) or t.state == "Running"
        def undo(r):
            if not r or not r.get("backup"): return
            kit.b.register(r["path"], Path(r["backup"]).read_text("utf-16")); kit.changed.pop(r["path"], None)
        return [Action("popup_headless", f"让 {path} 无窗口运行", "medium", "full", relief=float(n), reason="整份原任务存档，可原样还原；事后真跑一次校验", confident=True, value_s=min(3600.0, n * PER_FLASH_S * 24),
                       dry_run=dry, run=run, verify=verify, undo=undo,
                       done_text=lambda xs: f"把计划任务 {path}（{u.what[:30]}）改成无窗口启动，任务本身没动",
                       done_short=lambda xs: f"{path.lstrip(chr(92))} 不再弹黑窗")]


# ---------------- 2) 陈旧/重复/弃置的后台进程 ----------------
INTERP = {"python", "pythonw", "node", "powershell", "pwsh", "cmd", "java", "deno", "bun", "ruby"}


class ProcCtl:
    def __init__(self): import psutil; self.ps = psutil
    def get(self, pid, ctime):
        try:
            p = self.ps.Process(pid); return p if abs(p.create_time() - ctime) < 1 else None
        except Exception: return None
    def suspend(self, pid, ctime): p = self.get(pid, ctime); p and p.suspend(); return bool(p)
    def resume(self, pid, ctime): p = self.get(pid, ctime); p and p.resume(); return bool(p)
    def suspended(self, pid, ctime): p = self.get(pid, ctime); return bool(p) and p.status() == "stopped"


class ProcKit:
    def __init__(self, view, ctl, home: Path, clock=time.time, max_cands=12):
        self.view, self.ctl, self.home, self.clock, self.max_cands = view, ctl, Path(home), clock, max_cands; self.journal = self.home / "inv_suspended.json"
    def _j(self): return json.loads(self.journal.read_text("utf-8")) if self.journal.exists() else {}
    def _jw(self, d): self.home.mkdir(parents=True, exist_ok=True); self.journal.write_text(json.dumps(d), "utf-8")
    def resume_all(self) -> int:
        n = 0
        for k, v in list(self._j().items()):
            try: self.ctl.resume(v["pid"], v["ctime"]); n += 1
            except Exception: pass
        self._jw({}); return n
    def _roots(self, procs) -> list:
        out = []
        for p in procs.values():
            if Path(p.exe or p.name).stem.lower() not in INTERP or not program_sig(p)[1]: continue      # 只看解释器跑的“具名程序”；交互式终端（没有脚本/模块）不算
            par = procs.get(p.ppid)
            if par and program_sig(par) == program_sig(p) and par.create_time <= p.create_time: continue      # 只看“根”
            out.append(p)
        return out
    def discover(self, w) -> list:
        procs = self.view.procs(); cache = dict(procs=procs); roots = self._roots(procs); cands = []; groups: dict = {}
        for p in roots: groups.setdefault(family_sig(p), []).append(p)
        for sg, ps in groups.items():
            if len(ps) < 2: continue
            ps.sort(key=lambda p: p.create_time)
            for p in ps[:-1]: cands.append(self._cand("dup_process", p, cache, [q.pid for q in ps]))
        seen = {c.ctx["pid"] for c in cands}
        for p in roots:
            par = procs.get(p.ppid)
            if p.pid in seen or (par and par.create_time <= p.create_time): continue
            if self.view.now() - p.create_time > 6 * 3600 and not p.has_window: cands.append(self._cand("orphan_process", p, cache, []))
        return cands[: self.max_cands]
    def _cand(self, kind, p, cache, sibs) -> Candidate:
        return Candidate("process", f"proc:{p.pid}:{int(p.create_time)}", f"进程 {p.name}({p.pid}) {' '.join(p.cmdline[1:3])[:60]}", dict(signal=kind, rss_mb=p.rss_mb, age_s=self.view.now() - p.create_time, severity=min(1.0, 0.2 + p.rss_mb / 1500), need=1.0, unit="个"),
                         dict(pid=p.pid, ctime=p.create_time, _cache=cache, siblings=sibs))
    def judge(self, c, facts) -> Understanding:
        u = default_judge(c, facts); u.what = facts.get("cmdline", "")[:120]; u.owner = facts.get("root", "")
        return u
    def recheck(self, c, w) -> float:
        return 0.0 if (not self.ctl.get(c.ctx["pid"], c.ctx["ctime"]) or self.ctl.suspended(c.ctx["pid"], c.ctx["ctime"])) else 1.0
    def propose(self, c, u, w) -> list:
        kit = self; pid, ct = c.ctx["pid"], c.ctx["ctime"]; rss = c.signals.get("rss_mb", 0)
        def run():
            if not kit.ctl.suspend(pid, ct): raise RuntimeError("进程已不在或已换人")
            j = kit._j(); j[str(pid)] = dict(pid=pid, ctime=ct, ts=kit.clock(), why=u.why); kit._jw(j); return dict(pid=pid, ctime=ct)
        def undo(r):
            if r: kit.ctl.resume(r["pid"], r["ctime"]); j = kit._j(); j.pop(str(r["pid"]), None); kit._jw(j)
        return [Action("proc_suspend", f"挂起 {pid}", "medium", "full", relief=1.0, reason=u.why, confident=True, value_s=max(60.0, rss * 2),
                       dry_run=lambda: bool(kit.ctl.get(pid, ct)), run=run, verify=lambda r: kit.ctl.suspended(pid, ct), undo=undo,
                       done_text=lambda xs: f"挂起了陈旧进程 {pid}（{u.why}），没杀，可恢复", done_short=lambda xs: f"挂起陈旧进程 {pid}")]


def throttled(fn, secs, clock=time.time):
    st = dict(t=-1e18, v=[])
    def f(w):
        if clock() - st["t"] >= secs: st["v"] = fn(w); st["t"] = clock()
        return st["v"]
    return f


def register_all(ireg: InvestigatorRegistry, popup: PopupKit | None, proc: ProcKit | None, clock=time.time, poll_s=60.0):
    register_generic(ireg)
    if popup:
        ireg.discoverer("console_popups", throttled(popup.discover, 10.0, clock))
        ireg.gatherer("task_provenance", lambda c: c.kind == "task_popup", popup.g_task)
        ireg.judge("task_popup", popup.judge); ireg.responder("task_popup", popup.propose, popup.recheck)
    if proc:
        ireg.discoverer("stale_processes", throttled(proc.discover, poll_s, clock))
        ireg.judge("process", proc.judge); ireg.responder("process", proc.propose, proc.recheck)
    return ireg


def build(home: Path, live=False, apply_real=False, log=print, view=None, backend=None, observer=None, ctl=None, clock=time.time):
    """给 live.py / 干跑脚本用：返回 (场景, 工具包)。live 且 apply_real 才会真的动；否则只调查+写理解记录。"""
    home = Path(home); view = view or RealSysView(); ireg = InvestigatorRegistry()
    popup = PopupKit(backend or RealTaskBackend(home), observer or ConsoleObserver(home), view, home, clock)
    proc = ProcKit(view, ctl or ProcCtl(), home, clock); register_all(ireg, popup, proc, clock)
    inv = Investigator(ireg, view, home, clock, log); sc = investigator_scenario(ireg, inv, live=bool(live and apply_real), log=log, name="investigate_annoyances")
    if live and apply_real:
        import atexit; atexit.register(proc.resume_all)
    return sc, dict(popup=popup, proc=proc, inv=inv, ireg=ireg)