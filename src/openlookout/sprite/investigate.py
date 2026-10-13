"""通用“先调查、再动手”机制（investigate-then-act）。核心不认识任何具体问题；一切都是注册的插件：
  发现器 discoverer(world) -> [Candidate]   传感器：异常/代价/僵局等通用信号立案（不预设「是不是网络」）
  取证器 gatherer(applies, fn)             凑证据包（进程/日志/窗口/可选触发截图…）
  裁判   judge[kind](cand, facts)          本地仅安全闸+证据整理；**问题定性默认交给 novel（云端）**
  响应器 responder[kind](cand, u, world)   白名单可逆动作；recheck 直到解除
通用环：观察 → 取证 → 云端理解（默认）→ 白名单执行 → recheck。
本地 = 传感器 + 白名单 + 预算；理解 = novel/cloud。网络等只是插件之一。
理解记录写入 understandings.jsonl。act=True 且置信够 → Problem → Engine。
dry（live=False）：只调查、写「我会怎么做」，不产生动作。"""
from __future__ import annotations
import json, os, subprocess, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from .framework import Problem, Action, Scenario

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
STATES = ("in_use", "under_development", "abandoned", "stale_duplicate", "vendor", "protected", "self", "unknown")


@dataclass
class Candidate:
    kind: str
    key: str
    title: str
    signals: dict = field(default_factory=dict)     # 发现它的通用信号：recurrence / visible / rss_mb / age_s / duplicate_of ... 以及 severity/need/unit
    ctx: dict = field(default_factory=dict)


@dataclass
class Understanding:
    key: str
    kind: str
    title: str
    what: str = ""
    owner: str = ""
    state: str = "unknown"
    confidence: float = 0.0
    evidence: list = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    act: bool = False
    why: str = ""                                    # 为什么动/为什么不动
    ts: float = 0.0

    def line(self) -> str:
        return f"{self.title}｜{self.state}（置信{self.confidence:.2f}）｜{self.what}｜{'动手：' if self.act else '不动：'}{self.why}"

    def to_dict(self):
        d = dict(self.__dict__); d["facts"] = {k: v for k, v in self.facts.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
        return d


@dataclass
class ProcInfo:
    pid: int
    ppid: int
    name: str
    exe: str = ""
    cmdline: list = field(default_factory=list)
    cwd: str = ""
    create_time: float = 0.0
    rss_mb: float = 0.0
    cpu_s: float = 0.0
    ports: list = field(default_factory=list)       # 监听端口
    has_window: bool = False                         # 有可见顶层窗口
    foreground: bool = False
    open_files: list = field(default_factory=list)


class RealSysView:
    """真实系统视图（psutil + ctypes）；测试里换成假的。"""
    def __init__(self): import psutil; self.ps = psutil
    def now(self): return time.time()
    def self_pid(self): return os.getpid()
    def _windows(self):
        wins, fg = set(), None
        if os.name != "nt": return wins, fg
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32; pid = wintypes.DWORD()
        fg_h = u.GetForegroundWindow()
        if fg_h: u.GetWindowThreadProcessId(fg_h, ctypes.byref(pid)); fg = pid.value
        def cb(h, _):
            if u.IsWindowVisible(h) and u.GetWindowTextLengthW(h) > 0:
                p = wintypes.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(p)); wins.add(p.value)
            return True
        u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
        return wins, fg
    def procs(self) -> dict:
        ps = self.ps; out = {}; ports = {}
        try:
            for c in ps.net_connections(kind="inet"):
                if c.status == "LISTEN" and c.pid: ports.setdefault(c.pid, []).append(c.laddr.port)
        except Exception: pass
        wins, fg = self._windows()
        for p in ps.process_iter(["pid", "ppid", "name", "exe", "cmdline", "cwd", "create_time", "memory_info", "cpu_times"]):
            i = p.info
            try:
                out[i["pid"]] = ProcInfo(i["pid"], i["ppid"] or 0, (i["name"] or "").lower(), i["exe"] or "", list(i["cmdline"] or []), i["cwd"] or "", i["create_time"] or 0.0,
                                         (i["memory_info"].rss / 2**20) if i["memory_info"] else 0.0, (i["cpu_times"].user + i["cpu_times"].system) if i["cpu_times"] else 0.0,
                                         ports.get(i["pid"], []), i["pid"] in wins, i["pid"] == fg)
            except Exception: continue
        return out
    def open_files(self, pid) -> list:
        try: return [f.path for f in self.ps.Process(pid).open_files()][:50]
        except Exception: return []
    def newest_mtime(self, root, depth=3, cap=6000):
        """root 下最近一次“人改过的文件”的时间（忽略 .开头目录、__pycache__、node_modules、日志/缓存/流水文件）。"""
        best = None; n = 0; root = str(root); base = root.rstrip("\\/").count(os.sep)
        skip_ext = (".log", ".pyc", ".jsonl", ".pid", ".tmp", ".lock", ".png")
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("__pycache__", "node_modules")]
            if d.count(os.sep) - base >= depth: dirs[:] = []
            for f in files:
                if f.lower().endswith(skip_ext): continue
                n += 1
                if n > cap: return best
                try: m = os.path.getmtime(os.path.join(d, f))
                except OSError: continue
                if best is None or m > best: best = m
        return best
    def git_root(self, path):
        p = Path(path)
        for q in [p] + list(p.parents)[:6]:
            if (q / ".git").exists(): return str(q)
        return None
    def git_dirty(self, root):
        try:
            r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=6, creationflags=NO_WINDOW)
            return len([l for l in r.stdout.splitlines() if l.strip()]) if r.returncode == 0 else None
        except Exception: return None
    def read_head(self, path, n=4000):
        try: return Path(path).read_text("utf-8", errors="replace")[:n]
        except Exception: return ""
    def exists(self, path): return os.path.exists(path)


class InvestigatorRegistry:
    def __init__(self):
        self.discoverers: dict[str, Callable] = {}
        self.gatherers: list[tuple] = []             # (name, applies(cand)->bool, fn(cand, facts, world, view)->[str])
        self.judges: dict[str, Callable] = {}
        self.responders: dict[str, Callable] = {}
        self.rechecks: dict[str, Callable] = {}
    def discoverer(self, name, fn): self.discoverers[name] = fn; return fn
    def gatherer(self, name, applies, fn): self.gatherers.append((name, applies, fn)); return fn
    def judge(self, kind, fn): self.judges[kind] = fn; return fn
    def responder(self, kind, propose, recheck): self.responders[kind] = propose; self.rechecks[kind] = recheck


class Investigator:
    def __init__(self, ireg: InvestigatorRegistry, view, home: Path, clock=time.time, log=lambda *a: None,
                 novel=None, novel_min_conf: float = 0.75, prefer_novel: bool = True):
        self.ireg, self.view, self.home, self.clock, self.log = ireg, view, Path(home), clock, log
        self.novel = novel                           # NovelUnderstander：open 问题默认云端定性
        self.novel_min_conf = novel_min_conf
        self.prefer_novel = prefer_novel             # True：不靠「本地套路失败才升级」
        self.cache: dict[str, tuple] = {}            # key -> (ts, Understanding)
        self.ttl = 120.0
        self.state: dict = {}                         # 取证器的跨轮记忆（如 CPU 读数）
        self.file = self.home / "understandings.jsonl"

    def investigate(self, cand: Candidate, world=None, force=False) -> Understanding:
        now = self.clock(); hit = self.cache.get(cand.key)
        if hit and not force and now - hit[0] < self.ttl: return hit[1]
        facts: dict = dict(_state=self.state); ev: list = []
        for name, applies, fn in self.ireg.gatherers:
            try:
                if applies(cand): ev.extend(fn(cand, facts, world, self.view) or [])
            except Exception as e: ev.append(f"[取证 {name} 出错：{type(e).__name__}]")
        facts.pop("_state", None)
        judge = self.ireg.judges.get(cand.kind) or default_judge
        u = judge(cand, facts)
        u.evidence = ev + u.evidence; u.facts = facts; u.ts = now
        # 默认：open 问题交给云端 novel 定性（本地 judge 不是主理解）
        if self.novel is not None:
            try:
                from .novel import needs_novel
                if needs_novel(u, self.novel_min_conf, prefer_novel=self.prefer_novel):
                    vision_caption = ""
                    if facts.get("vision_kind"):
                        vision_caption = f"{facts.get('vision_kind')} stuck={facts.get('vision_stuck')} conf={facts.get('vision_confidence')}"
                    # 把 prefer_novel 同步到 understander（若有该字段）
                    if hasattr(self.novel, "prefer_novel"):
                        self.novel.prefer_novel = self.prefer_novel
                    nu = self.novel.understand(
                        cand, facts, u.evidence, prior=u,
                        vision_caption=vision_caption, force=force,
                    )
                    if nu is not None:
                        local = u
                        merged_facts = dict(facts)
                        merged_facts.update(nu.facts or {})
                        # 保留取证里的白名单线索（restartable 等），避免被空值盖掉
                        for k, v in facts.items():
                            if k not in merged_facts or merged_facts[k] in (None, "", [], {}):
                                merged_facts[k] = v
                        nu.facts = merged_facts
                        nu.evidence = list(dict.fromkeys((local.evidence or []) + (nu.evidence or [])))
                        # 理解归 novel；若 novel 拒动但本地已有高置信白名单路径，仍放行执行器
                        if (not nu.act) and local.act and local.confidence >= self.novel_min_conf:
                            nu.act = True
                            nu.facts["act_from_local_whitelist"] = True
                        u = nu
            except Exception as e:
                self.log(f"新颖理解跳过：{type(e).__name__}: {e}")
        if not hit or (hit[1].state, hit[1].act) != (u.state, u.act):
            try:
                self.home.mkdir(parents=True, exist_ok=True)
                with self.file.open("a", encoding="utf-8") as f: f.write(json.dumps(u.to_dict(), ensure_ascii=False, default=str) + "\n")
            except Exception: pass
            self.log("理解：" + u.line())
        self.cache[cand.key] = (now, u)
        return u


def default_judge(cand: Candidate, facts: dict) -> Understanding:
    """本地安全闸 + 证据整理（不是主理解）。种类专属裁判可覆盖取证后的白名单线索；
    问题「是什么」默认由 novel 定性。证据不足 = 不动。"""
    u = Understanding(cand.key, cand.kind, cand.title, what=facts.get("what", ""), owner=facts.get("owner", ""))
    if facts.get("is_self"): u.state, u.confidence, u.why = "self", 1.0, "这是我自己（或我的父/子进程）"; return u
    if facts.get("protected"): u.state, u.confidence, u.why = "protected", 1.0, facts["protected"]; return u
    if facts.get("dependents"): u.state, u.confidence, u.why = "in_use", 0.9, "有东西依赖它：" + facts["dependents"]; return u
    if facts.get("foreground") or facts.get("has_window") and facts.get("user_recent"):
        u.state, u.confidence, u.why = "in_use", 0.9, "你正在和它交互"; return u
    age, dev = facts.get("age_s"), facts.get("dev_recent_s")
    sib = facts.get("newer_sibling")
    if sib:
        fo = sib.get("family_only")
        if sib["sib_age_s"] < 60 or (age is not None and age < 300): u.state, u.confidence, u.why = "in_use", 0.6, "新实例刚起来/它刚启动，可能在重启过渡中，不动"; return u
        c = 0.9 if facts.get("same_args") and not fo else (0.8 if sib.get("is_self") and not fo else 0.6)
        if fo: c = 0.78 if (facts.get("orphan") and age and age >= 3600 and sib["newer_by_s"] >= 600 and sib["sib_age_s"] >= 600) else 0.5
        if not facts.get("orphan"): c = min(c, 0.6)          # 父进程还活着：可能是它在管着，证据不足
        u.state, u.confidence = "stale_duplicate", c
        if c >= 0.75: u.act, u.why = True, f"更新的{'同家族' if fo else '同一程序'}实例 pid {sib['pid']} 已稳定运行 {sib['sib_age_s']/60:.0f} 分钟（比它晚启动 {sib['newer_by_s']/60:.0f} 分钟），这个没人依赖、没有存活的父进程"
        else: u.why = f"有更新的{'同家族' if fo else '同一程序'}实例 pid {sib['pid']}，但证据不足（参数不同/新实例太年轻/父进程还在）"
        return u
    if facts.get("orphan") and age and age > 6 * 3600 and dev is not None and dev > 86400 and not facts.get("active_peers"):
        u.state, u.confidence, u.act, u.why = "abandoned", 0.8, True, f"父进程已不在、{age/3600:.0f} 小时前启动、它所在的项目 {dev/86400:.0f} 天没人改过、没人依赖"; return u
    if dev is not None and dev < 86400 or facts.get("active_peers"):
        u.state, u.confidence, u.why = "under_development", 0.8, "所在项目最近有人在改/有开发会话在跑，当作正在使用"; return u
    u.why = "证据不足"; return u


# ---------------- 通用取证器（注册到 ireg；作用于带 pid 的候选） ----------------
def has_pid(c: Candidate) -> bool: return c.ctx.get("pid") is not None


def g_provenance(c, facts, world, view):
    P = view.procs() if "procs" not in c.ctx.get("_cache", {}) else None
    procs = c.ctx.setdefault("_cache", {}).setdefault("procs", P or {})
    p = procs.get(c.ctx["pid"])
    if not p: facts["gone"] = True; return ["进程已不存在"]
    chain = []; q = p; seen = set()
    while q and q.pid not in seen and len(chain) < 5:
        seen.add(q.pid); chain.append(f"{q.name}({q.pid})"); q = procs.get(q.ppid)
    facts["orphan"] = p.ppid not in procs or procs[p.ppid].create_time > p.create_time
    facts["parent_chain"] = chain; facts["cmdline"] = " ".join(p.cmdline)[:300]; facts["cwd"] = p.cwd
    facts["age_s"] = view.now() - p.create_time; facts["rss_mb"] = p.rss_mb; facts["has_window"] = p.has_window; facts["foreground"] = p.foreground
    me = view.self_pid(); anc = set(); q = procs.get(me)
    while q and q.pid not in anc: anc.add(q.pid); q = procs.get(q.ppid)
    desc = {x.pid for x in procs.values() if _is_desc(x, p.pid, procs)}
    facts["is_self"] = p.pid == me or p.pid in anc or me in desc
    return [f"来源链：{' ← '.join(chain)}", f"{'没有' if facts['orphan'] else '有'}存活的父进程", f"启动于 {time.strftime('%m-%d %H:%M', time.localtime(p.create_time))}（{facts['age_s']/3600:.1f} 小时前）", f"内存 {p.rss_mb:.0f}MB"]


def _is_desc(x, root_pid, procs):
    n = 0
    while x and n < 8:
        if x.ppid == root_pid: return True
        x = procs.get(x.ppid); n += 1
    return False


def g_root_and_dev(c, facts, world, view):
    """项目根（git 根/脚本目录/cwd）、最近谁改过、git 是否有未提交改动、是否有别的开发会话在跑。"""
    procs = c.ctx["_cache"]["procs"]; p = procs.get(c.ctx["pid"])
    if not p: return []
    cand_path = None
    for a in p.cmdline[1:]:
        if not a.startswith("-") and (":" in a or "/" in a or "\\" in a) and view.exists(a): cand_path = a; break
    base = str(Path(cand_path).parent) if cand_path else p.cwd
    if not base or base.lower().startswith("c:\\windows"): return []
    root = view.git_root(base) or base; facts["root"] = root
    m = view.newest_mtime(root); out = [f"项目目录：{root}"]
    if m: facts["dev_recent_s"] = view.now() - m; out.append(f"目录里最近一次改动：{facts['dev_recent_s']/3600:.1f} 小时前")
    d = view.git_dirty(root) if view.git_root(base) else None
    if d is not None: facts["git_dirty"] = d; out.append(f"git 未提交改动 {d} 处")
    rl = root.lower().rstrip("\\/"); peers = []
    mine = {c.ctx["pid"]} | set(c.ctx.get("siblings", []))
    for q in procs.values():
        if q.pid in mine or q.pid == p.pid or q.name in ("conhost.exe", "openconsole.exe"): continue
        if (q.cwd.lower().startswith(rl) or any(rl in a.lower() for a in q.cmdline)) and view.now() - q.create_time < 1800 and not _is_desc(q, p.pid, procs):
            peers.append(f"{q.name}({q.pid}) 启动 {(view.now()-q.create_time)/60:.0f} 分钟前")
    if peers: facts["active_peers"] = peers[:5]; out.append("同项目下有最近才启动的开发/测试进程：" + "；".join(peers[:3]))
    return out


def g_dependents(c, facts, world, view):
    procs = c.ctx["_cache"]["procs"]; p = procs.get(c.ctx["pid"])
    if not p: return []
    kids = [q for q in procs.values() if q.ppid == p.pid and q.name not in ("conhost.exe", "openconsole.exe")]
    dep = []
    if kids: dep.append(f"{len(kids)} 个子进程（{', '.join(k.name for k in kids[:3])}）")
    if p.ports: dep.append(f"监听端口 {p.ports[:3]}")
    of = view.open_files(p.pid); facts["open_files"] = of[:5]
    if dep: facts["dependents"] = "；".join(dep)
    return ["谁依赖它：" + ("；".join(dep) if dep else "没发现子进程/监听端口")] + ([f"打开的文件：{of[:2]}"] if of else [])


def g_newer_sibling(c, facts, world, view):
    """同一程序的其它实例里，有没有更新、仍在跑的。先看“完全同一程序”（可执行+完整模块/脚本）；没有再看“同一家族”（模块顶层包相同，如旧预览版 vs 新版）。"""
    procs = c.ctx["_cache"]["procs"]; p = procs.get(c.ctx["pid"])
    if not p: return []
    now = view.now()
    def newest(fn):
        best = None
        for q in procs.values():
            if q.pid != p.pid and fn(q) == fn(p) and q.create_time > p.create_time + 5 and (best is None or q.create_time > best.create_time): best = q
        return best
    newer, fam = newest(program_sig), None
    if not newer: newer = fam = newest(family_sig)
    if not newer: return ["没有更新的同类实例在跑"]
    facts["newer_sibling"] = dict(pid=newer.pid, newer_by_s=newer.create_time - p.create_time, sib_age_s=now - newer.create_time, family_only=bool(fam), is_self=newer.pid == view.self_pid())
    facts["same_args"] = _argset(newer) == _argset(p)
    return [f"更新的{'同家族' if fam else '同一程序'}实例：pid {newer.pid}（晚 {(newer.create_time-p.create_time)/60:.0f} 分钟，已运行 {(now-newer.create_time)/60:.0f} 分钟），参数{'相同' if facts['same_args'] else '不同'}"]


def family_sig(p: ProcInfo):
    e, i = program_sig(p); return (e, i.split(".")[0] if i.startswith("-m ") else i)


def program_sig(p: ProcInfo):
    exe = Path(p.exe or p.name).stem.lower().replace("pythonw", "python"); a = p.cmdline[1:]; ident = ""
    for i, x in enumerate(a):
        if x == "-m" and i + 1 < len(a): ident = "-m " + a[i + 1].lower(); break
        if not x.startswith("-"): ident = x.lower(); break
    return (exe, ident)


def _argset(p: ProcInfo): return tuple(sorted(x.lower() for x in p.cmdline[1:] if any(ch in x for ch in "\\/:") or x.isdigit()))


def register_generic(ireg: InvestigatorRegistry):
    ireg.gatherer("provenance", has_pid, g_provenance)
    ireg.gatherer("root_and_dev", has_pid, g_root_and_dev)
    ireg.gatherer("dependents", has_pid, g_dependents)
    ireg.gatherer("newer_sibling", has_pid, g_newer_sibling)
    return ireg


def investigator_scenario(ireg: InvestigatorRegistry, inv: Investigator, live=False, min_conf=0.75, log=print, name="investigator") -> Scenario:
    """把“发现→调查→理解记录→（可信才）动手”接成一个 framework 场景。"""
    plans: dict = {}
    def detect(w):
        out = []
        for dn, disc in list(ireg.discoverers.items()):
            try: cands = disc(w) or []
            except Exception as e: log(f"发现器 {dn} 出错：{type(e).__name__}: {e}"); continue
            for c in cands:
                u = inv.investigate(c, w)
                if not (u.act and u.confidence >= min_conf): continue
                rc = ireg.rechecks.get(c.kind)
                if not rc: continue
                need = float(c.signals.get("need", 1.0))
                out.append(Problem(f"investigate:{c.kind}", float(c.signals.get("severity", 0.4)), u.line(), need=need, unit=c.signals.get("unit", ""), key=c.key,
                                   ctx=dict(cand=c, u=u), recheck=(lambda c=c: rc(c, w))))
        return out
    def propose(pb, w):
        c, u = pb.ctx["cand"], pb.ctx["u"]; fn = ireg.responders.get(c.kind)
        if not live:
            if c.key not in plans: plans[c.key] = u.line(); log("【干跑·不动手】" + u.line())
            return []
        acts = fn(c, u, w) if fn else []
        # 本地 responder 空、但新颖理解给了白名单可逆动作 → 记笔记等
        if not acts and (u.facts or {}).get("novel_actions"):
            try:
                from .novel import propose_novel_actions
                acts = propose_novel_actions(c, u, w)
            except Exception:
                acts = []
        return acts
    sc = Scenario(name, detect, propose,
                  group_text=lambda acts, pb: "；".join(a.done_text([a]) for a in acts) + "。理解记录已写入 understandings.jsonl，可一键撤销。",
                  group_short=lambda acts, pb: "、".join((a.done_short or a.done_text)([a]) for a in acts[:2]) + ("等" if len(acts) > 2 else ""))
    sc.plans = plans
    return sc