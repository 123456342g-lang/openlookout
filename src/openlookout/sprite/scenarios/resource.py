"""场景：内存/磁盘压力。检测=PressureDetector（阈值+变化率，边沿触发）；动作=隔离可再生文件、挂起闲置进程。
仅通过 registry.register 接入，不改核心。"""
from __future__ import annotations
import os, time
from dataclasses import dataclass, field
from pathlib import Path
from ..framework import Problem, Action, Scenario
from ..pressure import PressureDetector
from .. import risk as R
from ..quarantine import Quarantine


@dataclass
class World:
    snap: object = None
    env: R.Env = None
    q: Quarantine = None
    ctrl: object = None
    scan_limit: int = 20000
    home: Path = None
    router: object = None
    signals: list = field(default_factory=list)        # 观察到的行为信号：{"kind":"web_search|git_clone|pip_install","text":...}
    refresh: object = None                             # 重新读一次真实系统状态（判断压力是否已解除）
    suspended: dict = field(default_factory=dict)      # pid -> 进程名（我们挂起的，切回浏览器要恢复）


def _size(n):
    return f"{n/2**30:.1f}GB" if n >= 2**30 else f"{n/2**20:.0f}MB"


def _scan(world):
    """有界扫描候选：缓存目录、下载目录的安装包、用户目录里的 node_modules 和大旧文件。"""
    e = world.env; seen = 0
    roots = list(e.temp_dirs) + list(e.browser_cache_dirs) + list(e.pkg_cache_dirs) + ([e.downloads] if e.downloads else []) + list(e.user_dirs)
    for r in roots:
        for dp, dn, fn in os.walk(r):
            if "node_modules" in dn:
                yield Path(dp) / "node_modules", "dir"; dn.remove("node_modules")
            for f in fn:
                seen += 1
                if seen > world.scan_limit: return
                yield Path(dp) / f, "file"


def _mk_quarantine_action(world, items, label, risk, ask_text="", force=False, confident=False):
    """items: [(Path, Risk)]；一批同类。"""
    paths = [p for p, _ in items]
    size = sum(p.stat().st_size for p in paths if p.exists())
    def dry(): return all(p.exists() for p in paths) and (force and all(R.classify_file(p, world.env).reason == R.UNKNOWN_REASON for p in paths) or all(R.classify_file(p, world.env).level == risk for p in paths))
    def run():
        ids, skipped = [], []
        for p in paths:                                   # 动手前逐个重新核对（防止状态已变）
            if not p.exists() or (R.classify_file(p, world.env).level != risk and not (force and R.classify_file(p, world.env).reason == R.UNKNOWN_REASON)): skipped.append(str(p)); continue
            rk = R.classify_file(p, world.env); ids.append(world.q.put(p, label, regen=rk.regenerable, copy=rk.copy, now=world.env.now)["id"])
        return dict(ids=ids, skipped=skipped, bytes=size)
    def verify(r):
        held = {e["id"] for e in world.q.held()}
        return all(i in held for i in r["ids"]) and not any(p.exists() for p in paths if str(p) not in r["skipped"])
    def undo(r):
        for i in r["ids"]:
            try: world.q.restore(i)
            except (KeyError, FileNotFoundError): pass
    kind = "quarantine:" + label
    return Action(kind, f"隔离 {len(paths)} 个{label}", risk, "full", relief=size / 2**30, blast_items=len(paths), blast_bytes=size, confident=confident,
                  reason=items[0][1].reason, dry_run=dry, run=run, verify=verify, undo=undo,
                  done_text=lambda xs: f"清理了 {len(paths)} 个{label}（{_size(size)}，放进隔离区可还原）",
                  ask_text=ask_text or f"{len(paths)} 个{label}（{_size(size)}）",
                  done_short=lambda xs: f"清了 {len(paths)} 个{label}")


def _idle_background_browser(pr, critical: bool) -> bool:
    """A background browser can be suspended when memory is already critical.

    classify_proc only calls a browser safe when it is a ``--type=renderer``
    that has already been idle for 15 or 30 minutes. A plain sleeping browser
    therefore used to be skipped as high risk, and nothing was suspended or
    reported. Foreground, a visible window, and audio stay blocked. Below
    critical, the long renderer rule is unchanged.
    """
    name = pr.name.lower().removesuffix(".exe")
    if name not in R.BROWSERS:
        return False
    if pr.foreground_tree or pr.has_window or pr.audio:
        return False
    if pr.rss_mb < 100:
        return False
    scale = R.PROC_IDLE_SCALE
    if "--type=renderer" in (pr.cmdline or ""):
        need = (30 if critical else (1800 if pr.audio is None else 900)) * scale
        return pr.idle_s >= need and (critical or pr.rss_mb >= 150)
    if not critical:
        return False
    return pr.idle_s >= 30 * scale


def propose(pb: Problem, world: World):
    acts = []
    if pb.kind == "mem":
        critical = int((pb.ctx or {}).get("level") or 0) >= 2
        for pr in world.snap.procs:
            if pr.rss_mb < 100 or pr.pid in world.suspended: continue
            rk = R.classify_proc(pr)
            idle_browser = _idle_background_browser(pr, critical)
            if rk.level == "safe" or idle_browser:
                reason = rk.reason if rk.level == "safe" else "关键内存压力下的闲置后台浏览器，挂起即可，切回就恢复"
                def run(pr=pr):
                    if not world.ctrl.suspend(pr.pid, name=pr.name, rss_mb=pr.rss_mb): raise RuntimeError('suspend refused')
                    world.ctrl.trim(pr.pid); world.suspended[pr.pid] = pr.name
                    return dict(pid=pr.pid)
                def undo(r, pr=pr): world.ctrl.resume(r.get("pid", pr.pid)); world.suspended.pop(r.get("pid", pr.pid), None)
                def dry(pr=pr): return any(q.pid == pr.pid and q.name == pr.name and not q.foreground_tree for q in world.snap.procs)
                def ver(r): return r["pid"] in getattr(world.ctrl, "suspended", {r["pid"]})
                acts.append(Action("suspend:" + pr.name, f"挂起 {pr.name}#{pr.pid}", "safe", "full", relief=pr.rss_mb * 0.7, blast_items=1,
                                   reason=reason, dry_run=dry, run=run, verify=ver, undo=undo,
                                   done_text=lambda xs, pr=pr: f"暂停了 1 个{pr.name}后台进程", done_short=lambda xs: "停了 1 个后台进程",
                                   ask_text=""))
            else:
                acts.append(Action("proc:" + pr.name, f"{pr.name}#{pr.pid}", "high", "none", reason=rk.reason))
    else:
        groups = {}
        mediums = []
        for p, kind in _scan(world):
            rk = R.classify_dir(p, world.env) if kind == "dir" else R.classify_file(p, world.env)
            if kind == "dir":
                if rk.level == "medium": acts.append(Action("rm_node_modules", f"{p.parent.name}/node_modules", "medium", "none", reason=rk.reason, ask_text=f"{p.parent.name} 的 node_modules"))
                continue
            if rk.level == "safe": groups.setdefault(rk.reason.split("，")[0].split("：")[0], []).append((p, rk))
            elif rk.level == "medium": mediums.append((p, rk))
            else:
                acts.append(Action("file_high", p.name, "high", "none", reason=rk.reason))
                # 第 2 层：不认识的大文件类别，值得时才问模型一次，结论蒸馏成规则；模型永远不能把它升到 safe，只能到“问你”
                rt = getattr(world, "router", None)
                if rt and rk.reason == R.UNKNOWN_REASON and p.suffix.lower() not in R.USER_DOC_EXT and not world.env.under(p, world.env.user_dirs) and p.stat().st_size >= 100 * 2**20:
                    from ..tiers import sig_of
                    v, why = rt.classify_unknown(sig_of(p, p.stat().st_size), f"大小 {_size(p.stat().st_size)}，{(world.env.now - p.stat().st_mtime) / 86400:.0f} 天未改，目录 {p.parent.name}", value_s=pb.severity * 900 * min(1, p.stat().st_size / 2**30 / max(pb.need, 0.01)))
                    if v == "ask": acts.append(_mk_quarantine_action(world, [(p, R.Risk("medium", why))], "不认识的大文件（模型觉得可能是缓存）", "medium", ask_text=f"{p.name}（{_size(p.stat().st_size)}，{why}）", force=True))
        for label, items in groups.items():
            acts.append(_mk_quarantine_action(world, items, label, "safe"))
        for p, rk in mediums:
            if "副本" in rk.reason:
                acts.append(_mk_quarantine_action(world, [(p, rk)], "有副本的大旧文件", "medium", confident=True,
                                                  ask_text=f"{p.name}（{_size(p.stat().st_size)}，在 {Path(rk.reason.split('：')[-1]).parent.name} 里有逐字节核对过的同一份）"))
            else:
                acts.append(_mk_quarantine_action(world, [(p, rk)], "查不到来源的旧安装包", "medium",
                                                  ask_text=f"{p.name}（{_size(p.stat().st_size)}，旧安装包但查不到下载来源）"))
    return acts


def group_text(acted, pb):
    files = [a for a in acted if a.kind.startswith("quarantine")]
    procs = [a for a in acted if a.kind.startswith("suspend")]
    parts = []
    if files: parts.append(f"清理了 {sum(a.blast_items for a in files)} 个缓存/临时文件（共 {_size(sum(a.blast_bytes for a in files))}，可还原）")
    if procs: parts.append(f"暂停了 {len(procs)} 个闲置后台进程（约 {_size(sum(a.relief for a in procs) * 2**20)}，切回就恢复）")
    return "；".join(parts)


def group_short(acted, pb):
    n = sum(a.blast_items for a in acted if a.kind.startswith("quarantine")); k = sum(1 for a in acted if a.kind.startswith("suspend"))
    bits = ([f"清了 {n} 个缓存"] if n else []) + ([f"停了 {k} 个后台进程"] if k else [])
    return "、".join(bits) + "，可还原"


def make_recheck(det, world, p):
    """现在还剩多少需要缓解：重新读一次真实状态（world.refresh），读不到就用检测时的数。"""
    def rc():
        r = getattr(world, "refresh", None)
        if not r: return p.need
        s = r()
        if p.kind == "mem":
            return max(0.0, (det.p["mem_warn"] + 0.05) * s.mem_total_mb - s.mem_avail_mb) if s.mem_avail_mb / s.mem_total_mb < det.p["mem_warn"] + 0.05 else 0.0
        tot, free = s.disks.get(p.target, (1, 1)); return max(0.0, (det.p["disk_warn"] + 0.03) * tot - free)
    return rc


def make(detector: PressureDetector = None, world_getter=None) -> Scenario:
    det = detector or PressureDetector()
    def detect(world):
        out = []
        for p in det.update(world.snap):
            out.append(Problem(p.kind, p.level / 2, p.evidence, p.need, "GB" if p.kind == "disk" else "MB", key=f"{p.kind}:{p.target}",
                               ctx=dict(level=p.level), recheck=make_recheck(det, world, p)))
        return out
    def observe(world):
        # 状态驱动的恢复：用户回到浏览器，立刻恢复我们挂起的进程
        fg = (world.snap.foreground_name or "").lower()
        if fg in R.BROWSERS:
            for pid, name in list(world.suspended.items()):
                if name in R.BROWSERS: world.ctrl.resume(pid); world.suspended.pop(pid)
    return Scenario("resource_pressure", detect, propose, group_text, group_short, observe=observe)
