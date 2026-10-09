"""更多真实场景，全部只靠注册接入（核心零改动）。每个动作都有类型化的风险/可逆性，不确定一律当 high。
disk_prewarn / hung_cpu / dup_downloads / stale_build_dirs / startup_bloat / notification_flood / quarantine_expiry /
browser_tabs / battery_prewarn / homework_env_prep"""
from __future__ import annotations
import json, re, shutil, time
from collections import deque
from pathlib import Path
from ..framework import Problem, Action, Scenario
from .. import risk as R
from ..quarantine import sha
from . import resource


# ---------------------------------------------------------------- 1) 磁盘“预警”：按增长速度，在写满之前行动
def disk_prewarn(horizon_h=24, min_samples=3):
    hist = {}; armed = {}
    def detect(w):
        out = []
        for d, (tot, free) in w.snap.disks.items():
            h = hist.setdefault(d, deque(maxlen=12)); h.append((w.snap.t, free))
            if len(h) < min_samples or free / tot < 0.05: continue            # 已经危急的交给 resource_pressure
            (t0, f0), (t1, f1) = h[0], h[-1]
            rate = (f0 - f1) / max((t1 - t0) / 3600, 1e-6)                       # GB/小时
            ttf = free / rate if rate > 0.05 else None
            if ttf is not None and ttf < horizon_h and armed.get(d, True):
                armed[d] = False
                out.append(Problem("disk_prewarn", 0.5, f"{d} 每小时少 {rate:.1f}GB，约 {ttf:.0f} 小时后写满", need=max(0.0, rate * 72 - free) if False else rate * horizon_h - free + 0.1 * tot, unit="GB",
                                   key=f"prewarn:{d}", ctx=dict(disk=d)))
            if ttf is None or ttf > 2 * horizon_h: armed[d] = True
        return out
    def propose(pb, w): return resource.propose(Problem("disk", pb.severity, pb.evidence, pb.need, "GB"), w)
    return Scenario("disk_prewarn", detect, propose, resource.group_text, resource.group_short)


# ---------------------------------------------------------------- 2) 卡死进程霸占 CPU：降优先级（可恢复），不杀
def hung_cpu(busy_s=600):
    seen = set()
    def detect(w):
        out = []
        for p in w.snap.procs:
            if p.pid in seen or p.busy_s < busy_s or p.not_responding is not True: continue
            seen.add(p.pid); out.append(Problem("hung_cpu", 0.5, f"{p.name} 无响应且占满 CPU {p.busy_s/60:.0f} 分钟", key=f"hung:{p.pid}", ctx=dict(proc=p)))
        return out
    def propose(pb, w):
        p = pb.ctx["proc"]
        unsaved = any(m in (p.title or "") for m in ("*", "●", "未保存", "unsaved", "无标题"))
        if p.name in R.PROTECTED or p.foreground_tree or unsaved or p.name in R.EDITORS or p.audio is True or p.audio is None and p.has_window:
            return [Action("hung:" + p.name, f"{p.name}#{p.pid}", "high", "none", reason="受保护/前台/可能有未保存内容")]
        if not hasattr(w.ctrl, "set_priority"): return []
        def run(): return dict(pid=p.pid, prev=w.ctrl.set_priority(p.pid, "low"))
        return [Action("lower_priority", f"降低 {p.name} 优先级", "safe", "full", relief=0.5, reason="无响应+满载，降优先级不杀进程",
                       dry_run=lambda: any(q.pid == p.pid and q.name == p.name and not q.foreground_tree for q in w.snap.procs),
                       run=run, verify=lambda r: w.ctrl.prio.get(r["pid"]) == "low" if hasattr(w.ctrl, "prio") else True,
                       undo=lambda r: w.ctrl.set_priority(r["pid"], r["prev"] or "normal"),
                       done_text=lambda xs: f"{p.name} 卡死占满 CPU，我把它的优先级降低了（没有结束它）", done_short=lambda xs: f"{p.name} 卡住，已降优先级")]
    return Scenario("hung_cpu", detect, propose)


# ---------------------------------------------------------------- 3) 重复的大下载
def dup_downloads(min_mb=50):
    state = {"n": 0}
    def scan(w):
        d = w.env.downloads
        if not d or not Path(d).is_dir(): return []
        by = {}
        for p in Path(d).iterdir():
            if p.is_file() and not p.is_symlink() and p.stat().st_size >= min_mb * 2**20: by.setdefault(p.stat().st_size, []).append(p)
        groups = []
        for sz, fs in by.items():
            if len(fs) < 2: continue
            h = {}
            for p in fs: h.setdefault(sha(p), []).append(p)
            groups += [sorted(v, key=lambda p: (p.stat().st_mtime, p.name)) for v in h.values() if len(v) > 1]
        return groups
    def detect(w):
        g = scan(w); n = sum(len(x) - 1 for x in g)
        if n and n != state["n"]:
            state["n"] = n; return [Problem("dup_downloads", 0.3, f"下载夹里有 {n} 个大文件是逐字节相同的重复", key=f"dup:{n}", ctx=dict(groups=g))]
        if not n: state["n"] = 0
        return []
    DUP = re.compile(r"\(\d+\)|副本|[ _-]copy|复件", re.I)
    def propose(pb, w):
        acts = []
        for g in pb.ctx["groups"]:
            keep = g[0]
            for p in g[1:]:
                rk = R.classify_file(p, w.env)
                if str(p) in w.env.open_paths or str(keep) in w.env.open_paths or w.env.under(keep, w.env.temp_dirs): continue
                if (w.env.now - p.stat().st_mtime) < 7200: continue
                level = "safe" if (DUP.search(p.stem) and not DUP.search(keep.stem)) else "medium"       # 名字不像副本 -> 问
                def run(p=p, keep=keep):
                    if not p.exists() or sha(p) != sha(keep): return dict(ids=[], skipped=[str(p)])           # 动手前再核对一次字节
                    return dict(ids=[w.q.put(p, "重复下载", copy=str(keep), now=w.env.now)["id"]], skipped=[])
                acts.append(Action("dup_quarantine", f"收起重复 {p.name}", level, "full", relief=p.stat().st_size / 2**30, blast_bytes=p.stat().st_size, reason=f"与 {keep.name} 逐字节相同",
                                   dry_run=lambda p=p, keep=keep: p.exists() and keep.exists(), run=run,
                                   verify=lambda r, p=p: all(i in {e["id"] for e in w.q.held()} for i in r["ids"]) and (not r["ids"] or not p.exists()),
                                   undo=lambda r: [w.q.restore(i) for i in r["ids"]],
                                   done_text=lambda xs, p=p, keep=keep: f"{p.name} 和 {keep.name} 一模一样，把重复的收进了隔离区",
                                   done_short=lambda xs, p=p: f"收起重复下载 {p.name[:12]}", ask_text=f"{p.name}（和 {keep.name} 相同）"))
        return acts
    return Scenario("dup_downloads", detect, propose)


# ---------------------------------------------------------------- 4) 被遗忘的巨大构建目录
BUILD = {"target", "build", "dist", "out", ".gradle", ".next", ".nuxt", ".parcel-cache", ".turbo", ".pytest_cache", ".mypy_cache"}
MANIFESTS = ("Cargo.toml", "pom.xml", "build.gradle", "CMakeLists.txt", "package.json", "pyproject.toml", "setup.py", "Makefile")


def classify_build_dir(d: Path, env: R.Env, min_idle_days=60, min_mb=200) -> R.Risk:
    if d.is_symlink() or d.name not in BUILD: return R._high("不是已知的构建目录名")
    proj = d.parent
    if not any((proj / m).exists() for m in MANIFESTS): return R._high("旁边没有构建清单，无法确认可再生")
    if (d / ".git").exists() or (proj / ".git").exists() is False and False: return R._high("目录里有 .git")
    files = [p for p in d.rglob("*") if p.is_file()]
    if any(p.is_symlink() for p in d.rglob("*")): return R._high("有符号链接")
    if sum(p.stat().st_size for p in files) < min_mb * 2**20: return R._high("太小，不值得动")
    newest = max((p.stat().st_mtime for p in files), default=0)
    src_new = max((p.stat().st_mtime for p in proj.iterdir() if p.is_file()), default=0)
    if env.now - max(newest, src_new) < min_idle_days * 86400: return R._high("项目最近还在用")
    if any(str(proj) in (r.cwd or "") or str(proj) in (r.cmdline or "") for r in env.running): return R._high("有进程正在使用")
    if any(p.suffix.lower() in (".docx", ".xlsx", ".pptx", ".pdf", ".psd", ".key", ".pem", ".kdbx") and d.name in ("dist", "out") for p in files): return R._high("构建目录里混有文档类文件，可能是手工放的成果")
    if d.name in ("dist", "out") and not any((proj / m).exists() for m in MANIFESTS[:7]): return R._high("无法确认 dist/out 是构建产物")
    return R.Risk("safe", f"{proj.name}/{d.name}：{min_idle_days} 天没动的可再生构建目录", True, "quarantine")


def stale_build_dirs(roots_getter):
    state = {"seen": set()}
    def detect(w):
        out = []
        for r in roots_getter(w):
            for d in Path(r).rglob("*"):
                if d.is_dir() and d.name in BUILD and str(d) not in state["seen"] and not any(x in BUILD or x == "node_modules" for x in d.relative_to(r).parts[:-1]):
                    state["seen"].add(str(d))
                    if classify_build_dir(d, w.env).level != "high": out.append(Problem("stale_build", 0.3, f"{d.parent.name}/{d.name} 久未使用的构建目录", key=str(d), ctx=dict(dir=d)))
        return out
    def propose(pb, w):
        d = pb.ctx["dir"]; rk = classify_build_dir(d, w.env)
        if rk.level == "high": return [Action("build_dir_high", d.name, "high", "none", reason=rk.reason)]
        size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
        return [Action("build_dir", f"收起 {d.parent.name}/{d.name}", rk.level, "regen", relief=size / 2**30, blast_bytes=size, reason=rk.reason,
                       dry_run=lambda: classify_build_dir(d, w.env).level == "safe", run=lambda: dict(id=w.q.put_dir(d, "构建目录", regen=True, now=w.env.now)["id"]),
                       verify=lambda r: r["id"] in {e["id"] for e in w.q.held()} and not d.exists(), undo=lambda r: w.q.restore(r["id"]),
                       done_text=lambda xs: f"{d.parent.name}/{d.name}（{size/2**20:.0f}MB）很久没用，压缩收起（可由构建重新生成，也可还原）",
                       done_short=lambda xs: f"收起 {d.parent.name} 的旧构建（{size/2**20:.0f}MB）")]
    return Scenario("stale_build_dirs", detect, propose)


# ---------------------------------------------------------------- 5) 开机自启项膨胀
KEEP_STARTUP = re.compile(r"(defender|antivirus|security|firewall|杀毒|安全|驱动|driver|realtek|nvidia|intel|amd|input|ime|输入法|onedrive|dropbox|backup|备份|sync|同步|vpn|authenticator|bitlocker|touchpad|bluetooth)", re.I)


def startup_bloat(min_entries=12, unused_days=90):
    state = {"armed": True}
    def detect(w):
        ent = [e for e in getattr(w, "startup", []) if e.get("enabled", True)]
        if len(ent) >= min_entries and state["armed"]:
            state["armed"] = False; return [Problem("startup_bloat", 0.3, f"开机自启项有 {len(ent)} 个", key="startup")]
        if len(ent) < min_entries - 2: state["armed"] = True
        return []
    def propose(pb, w):
        acts = []
        for e in w.startup:
            if not e.get("enabled", True): continue
            lu = e.get("last_used_days")
            if lu is None or KEEP_STARTUP.search(e["name"] + " " + e.get("publisher", "")) or e.get("system"):
                acts.append(Action("startup_high", e["name"], "high", "none", reason="安全/驱动/输入法/同步类或使用情况未知")); continue
            if lu < unused_days: continue
            if not hasattr(w.ctrl, "startup_disable"): continue
            n = e["name"]
            acts.append(Action("startup_disable", f"关闭自启 {n}", "safe", "full", relief=e.get("impact_s", 1), reason=f"{lu} 天没用过", run=lambda n=n: (w.ctrl.startup_disable(n), dict(name=n))[1],
                               verify=lambda r: w.ctrl.startup.get(r["name"]) is False if hasattr(w.ctrl, "startup") else True,
                               undo=lambda r: w.ctrl.startup_enable(r["name"]), done_text=lambda xs, n=n: f"{n} 已经 {lu} 天没用过，关掉了它的开机自启（随时可恢复）",
                               done_short=lambda xs, n=n: f"关了 {n} 的开机自启"))
        return acts
    return Scenario("startup_bloat", detect, propose, group_short=lambda a, pb: f"关了 {len(a)} 个很久没用的开机自启")


# ---------------------------------------------------------------- 6) 通知洪水：定时静音，洪水退去就恢复（状态驱动）
KEEP_NOTIF = re.compile(r"(电话|通话|call|短信|sms|日历|calendar|闹钟|alarm|验证码|otp|authenticator|银行|bank|支付|alipay|pay|紧急|emergency|提醒|reminder|security|安全)", re.I)


def notification_flood(limit=30, window_s=600):
    def counts(w):
        c = {}
        for (app, t, cat) in getattr(w, "notifs", []):
            if w.env.now - t <= window_s: c.setdefault(app, []).append(cat)
        return c
    def detect(w):
        return [Problem("notif_flood", 0.3, f"{a} 十分钟内弹了 {len(v)} 条通知", key=f"notif:{a}", ctx=dict(app=a, cats=v)) for a, v in counts(w).items()
                if len(v) >= limit and a not in getattr(w, "muted_by_us", set())]
    def observe(w):
        c = counts(w)
        for a in list(getattr(w, "muted_by_us", set())):
            if len(c.get(a, [])) < 3: w.ctrl.unmute(a); w.muted_by_us.discard(a)      # 洪水退去，自动恢复
    def propose(pb, w):
        a, cats = pb.ctx["app"], pb.ctx["cats"]
        if KEEP_NOTIF.search(a) or any(KEEP_NOTIF.search(c or "") for c in cats) or any(c in ("direct", "mention", "call") for c in cats):
            return [Action("mute_high", a, "high", "none", reason="可能是电话/验证码/日历/@你")]
        if not hasattr(w.ctrl, "mute"): return []
        if not hasattr(w, "muted_by_us"): w.muted_by_us = set()
        def run(): w.ctrl.mute(a); w.muted_by_us.add(a); return dict(app=a)
        return [Action("mute_app", f"暂时静音 {a}", "safe", "full", relief=1, reason="大量低价值通知", run=run, verify=lambda r: a in getattr(w.ctrl, "muted", {a}),
                       undo=lambda r: (w.ctrl.unmute(a), w.muted_by_us.discard(a)), done_text=lambda xs: f"{a} 狂刷通知，先静音了它（刷完自动恢复）", done_short=lambda xs: f"{a} 刷屏，先静音")]
    return Scenario("notification_flood", detect, propose, observe=observe)


# ---------------------------------------------------------------- 7) 隔离区到期（状态驱动：磁盘紧张/隔离区变大时才评估）
def quarantine_expiry(days=14, min_bytes=1 * 2**30, tight_frac=0.15):
    state = {"sig": None}
    def detect(w):
        if not w.q: return []
        held = w.q.held(); size = sum(e["stored"] for e in held)
        tight = any(f / t < tight_frac for t, f in w.snap.disks.values())
        auto, ask = w.q.classify_expiry(w.env.now, days)
        sig = (len(auto), len(ask))
        if (auto or ask) and (tight or size >= min_bytes) and sig != state["sig"]:
            state["sig"] = sig
            return [Problem("quarantine_expiry", 0.3, f"隔离区 {size/2**20:.0f}MB，其中 {len(auto)+len(ask)} 项超过 {days} 天", key=f"qx:{sig}", ctx=dict(auto=auto, ask=ask))]
        return []
    def propose(pb, w):
        acts = []
        for e, why in pb.ctx["auto"]:
            def undo(r, e=e):
                c = e.get("copy")
                if c and Path(c).is_file() and not Path(e["orig"]).exists(): shutil.copy2(c, e["orig"])           # 有副本的可以补回
            acts.append(Action("expire_" + ("regen" if e.get("regen") else "copy"), f"永久清除隔离区 {Path(e['orig']).name}", "safe", "regen", relief=e["stored"] / 2**30,
                               blast_bytes=e["stored"], reason=f"超过 {days} 天，{why}", dry_run=lambda e=e, why=why: (e.get("regen") if why == "可再生" else bool(e.get("copy") and Path(e["copy"]).is_file() and sha(Path(e["copy"])) == e["sha"])),
                               run=lambda e=e: dict(ok=w.q.purge(e["id"], "expire")), verify=lambda r: r["ok"], undo=undo,
                               done_text=lambda xs, e=e, why=why: f"{Path(e['orig']).name} 在隔离区放了 {days} 天（{why}），已永久清除",
                               done_short=lambda xs: "清掉隔离区里过期的可再生项"))
        # 没有副本、也不可再生的过期项：不永久清除（不可还原就不做），继续留在隔离区
        return acts
    return Scenario("quarantine_expiry", detect, propose)


# ---------------------------------------------------------------- 8) 浏览器标签爆炸：只存档最老的超额标签，绝不关标签
def browser_tabs(limit=25):
    """w.snap.tabs 支持三种形态：int（标签总数）/ 列表（[{url,title,age_s}]）/ 字典（{浏览器: [标签]}）。
    数据源还没接（T1 的 sysstate）时 getattr 拿不到就不报（宁可漏做）。动作=把最老的超额标签网址
    存到我们的档案文件（只新建我们自己的文件，可整份撤销），标签本身一个不动。"""
    state = {"armed": True}

    def tabs_of(w):
        t = getattr(w.snap, "tabs", None)
        if t is None:
            return None, []
        if isinstance(t, int):
            return t, []
        if isinstance(t, (list, tuple)):
            items = [x for x in t if isinstance(x, dict)]
            items.sort(key=lambda x: x.get("age_s", 0), reverse=True)
            return len(t), items
        if isinstance(t, dict):
            items = []
            for browser, tabs in t.items():
                for tab in tabs:
                    items.append(dict(browser=browser, **({} if isinstance(tab, str) else tab)))
            items.sort(key=lambda x: x.get("age_s", 0), reverse=True)
            return len(items), items
        return None, []

    def detect(w):
        n, items = tabs_of(w)
        if n is None:
            return []
        if n > limit and state["armed"]:
            state["armed"] = False
            return [Problem("browser_tabs", 0.4, f"浏览器开了 {n} 个标签", need=n - limit, key="tabs",
                            ctx=dict(count=n, extra=items[: n - limit]))]
        if n <= limit:
            state["armed"] = True
        return []

    def propose(pb, w):
        extra = pb.ctx.get("extra") or []
        if not extra:
            return [Action("tabs_high", "标签", "high", "none", reason="没有可存档的额外标签")]
        if not w.home:
            return [Action("tabs_high", "标签", "high", "none", reason="没有档案目录")]
        fname = f"tabs_archive_{pb.key.replace(':', '_')}_{int(time.time()) % 100000}.jsonl"
        f = w.home / fname
        n = len(extra)
        def dry(): return not f.exists()
        def run():
            with f.open("w", encoding="utf-8") as fh:
                for it in extra:
                    fh.write(json.dumps(it, ensure_ascii=False) + "\n")
            return dict(path=str(f), n=n)
        def verify(r): return Path(r["path"]).exists() and r["n"] == n
        def undo(r):
            p = Path(r["path"])
            if p.name.startswith("tabs_archive_") and p.exists():
                p.unlink()                       # 只删我们自己的档案文件
        return [Action("tab_archive", f"存档 {n} 个最老标签", "safe", "full", relief=float(n), blast_items=n,
                       reason=f"标签超过 {limit} 个，先把最老的一批存档，不关标签",
                       dry_run=dry, run=run, verify=verify, undo=undo,
                       done_text=lambda xs: f"浏览器开了 {pb.ctx['count']} 个标签，最老的 {n} 个网址我存档了（标签没动，可撤销）",
                       done_short=lambda xs: f"存档 {n} 个老标签网址")]
    return Scenario("browser_tabs", detect, propose)


# ---------------------------------------------------------------- 9) 电量低于长任务前预警：暂停闲置后台进程省电（可恢复）
def battery_prewarn(threshold=20, busy_s=300):
    """w.snap.battery=(percent, charging)。电量 ≤ 阈值、未充电、且正有长任务（长时间满载非前台进程）时：
    把可安全挂起的闲置后台进程暂停省电（切回浏览器自动恢复/撤销即恢复）。数据没接（getattr 拿不到）就不报。
    recheck：电量回升到阈值以上或开始充电即解除。"""
    state = {"armed": True}

    def bat(w):
        b = getattr(w.snap, "battery", None)
        if not isinstance(b, (tuple, list)) or len(b) < 2:
            return None
        try:
            return float(b[0]), bool(b[1])
        except (TypeError, ValueError):
            return None

    def long_task(w):
        for p in getattr(w.snap, "procs", []) or []:
            if (getattr(p, "busy_s", 0) or 0) >= busy_s and (getattr(p, "rss_mb", 0) or 0) >= 200 and not getattr(p, "foreground_tree", False):
                return p
        return None

    def detect(w):
        b = bat(w); t = long_task(w)
        if b is None or t is None:
            return []
        pct, charging = b
        if charging or pct > threshold:
            state["armed"] = True
            return []
        if state["armed"]:
            state["armed"] = False
            def recheck():
                b2 = bat(w)
                if b2 is None:
                    return 0.0
                p2, c2 = b2
                return 0.0 if c2 or p2 > threshold else max(0.0, threshold - p2)
            return [Problem("battery_prewarn", 0.5, f"电量只剩 {pct:.0f}%，{t.name} 还在跑长任务", need=max(0.0, threshold - pct),
                            unit="%", key="battery", ctx=dict(pct=pct, task=t), recheck=recheck)]
        return []

    def propose(pb, w):
        acts = []
        for pr in getattr(w.snap, "procs", []) or []:
            rk = R.classify_proc(pr)
            if rk.level != "safe":
                acts.append(Action("battery_high", pr.name, "high", "none", reason=rk.reason))
                continue
            if pr.pid in getattr(w, "suspended", {}):
                continue
            if not hasattr(w.ctrl, "suspend"):
                continue
            def run(pr=pr):
                if not w.ctrl.suspend(pr.pid, name=pr.name, rss_mb=pr.rss_mb):
                    raise RuntimeError("suspend refused")
                if hasattr(w.ctrl, "trim"):
                    w.ctrl.trim(pr.pid)
                w.suspended[pr.pid] = pr.name
                return dict(pid=pr.pid)
            def undo(r, pr=pr):
                if hasattr(w.ctrl, "resume"):
                    w.ctrl.resume(r.get("pid", pr.pid))
                w.suspended.pop(r.get("pid", pr.pid), None)
            def dry(pr=pr):
                return any(q.pid == pr.pid and q.name == pr.name and not q.foreground_tree for q in getattr(w.snap, "procs", []) or [])
            def ver(r): return r["pid"] in getattr(w.ctrl, "suspended", {r["pid"]})
            acts.append(Action("battery_suspend", f"暂停 {pr.name} 省电", "safe", "full", relief=1.0, blast_items=1,
                               reason=f"电量低（{pb.ctx['pct']:.0f}%）且长任务在跑，暂停闲置后台进程省电",
                               dry_run=dry, run=run, verify=ver, undo=undo,
                               done_text=lambda xs, pr=pr: f"电量只剩 {pb.ctx['pct']:.0f}%，先把闲置的 {pr.name} 暂停省电（切回就恢复）",
                               done_short=lambda xs, pr=pr: f"暂停 {pr.name} 省电"))
        return acts
    def observe(w):
        # 状态驱动恢复：电量回升/开始充电，立刻恢复我们为省电暂停的进程（与 resource 的浏览器恢复同思路）
        b = bat(w)
        if b is None:
            return
        pct, charging = b
        if charging or pct > threshold:
            for pid, name in list(getattr(w, "suspended", {}).items()):
                if hasattr(w.ctrl, "resume"):
                    w.ctrl.resume(pid)
                w.suspended.pop(pid, None)
    return Scenario("battery_prewarn", detect, propose, observe=observe)


# ---------------------------------------------------------------- 10) 编号作业环境提前准备：建 venv（+装依赖/复制模板），全部可撤销
HOMEWORK_RE = re.compile(r"(作业|实验|assignment|hw|lab|练习)[\s_-]*\d+|\d+\s*(作业|实验|练习)|第\s*[一二三四五六七八九十\d]+\s*[课次章]", re.I)
PREP_MARKER = ".sprite_prep"


def homework_env_prep(install_deps=True, copy_templates=True, venv_cmd=None):
    """扫描 user_dirs / env.homework_dirs 里的编号作业目录（如 实验1 / 作业2 / hw3 / 第3课），
    没有 venv 的：建 .venv（真实环境默认用当前解释器 python -m venv，可注入 venv_cmd 供测试），
    requirements.txt 存在时顺带装依赖（装进我们建的 venv，撤销随 venv 一起消失），
    env.templates 目录存在时复制里面的模板文件（文件名记录进标记，撤销时只删我们复制的）。
    标记文件证明 venv 是我们建的：撤销只动我们创建的东西，绝不碰用户已有文件。"""
    state = {"seen": set()}

    def roots(w):
        rs = list(getattr(w.env, "homework_dirs", None) or [])
        for u in getattr(w.env, "user_dirs", None) or []:
            p = Path(u)
            if p.is_dir():
                rs.append(p)
        return rs

    def scan(w):
        out = []
        for r in roots(w):
            try:
                for d in r.iterdir():
                    if d.is_dir() and HOMEWORK_RE.search(d.name) and str(d) not in state["seen"]:
                        state["seen"].add(str(d))
                        has_venv = any((d / x).exists() for x in (".venv", "venv", "env"))
                        if not has_venv:
                            out.append(d)
            except OSError:
                continue
        return out

    def detect(w):
        need = scan(w)
        if not need:
            return []
        return [Problem("homework_env", 0.4, f"{len(need)} 个编号作业目录还没准备运行环境", need=float(len(need)), key="homework_env",
                        ctx=dict(dirs=need))]

    def propose(pb, w):
        acts = []
        for d in pb.ctx["dirs"]:
            marker = d / PREP_MARKER
            venv = d / ".venv"
            def dry(d=d): return d.is_dir() and not marker.exists() and not (d / ".venv").exists()
            def run(d=d):
                if not dry(d):
                    return dict(ok=False, why="状态已变")
                created = dict(dir=str(d), venv=".venv", copied=[], deps=False)
                # 1) venv（可注入命令；默认 python -m venv）
                cmd = venv_cmd or (lambda dd: __import__("subprocess").run(
                    [__import__("sys").executable, "-m", "venv", ".venv"], cwd=str(dd), check=True, timeout=600))
                try:
                    cmd(d)
                except Exception:
                    shutil.rmtree(d / ".venv", ignore_errors=True)
                    return dict(ok=False, why="venv 失败")
                # 2) 依赖：requirements.txt 存在时装进刚建的 venv（装失败整体撤销）
                req = d / "requirements.txt"
                if install_deps and req.exists():
                    pip = (d / ".venv" / "Scripts" / "pip.exe" if __import__("sys").platform == "win32" else d / ".venv" / "bin" / "pip")
                    if pip.exists():
                        try:
                            __import__("subprocess").run([str(pip), "install", "-r", "requirements.txt"], cwd=str(d), check=True, timeout=900)
                            created["deps"] = True
                        except Exception:
                            shutil.rmtree(d / ".venv", ignore_errors=True)
                            return dict(ok=False, why="依赖安装失败，已回滚 venv")
                # 3) 模板：env.templates 目录里的文件复制进作业目录（记录文件名，撤销只删这些）
                tpl = getattr(w.env, "templates", None)
                if copy_templates and tpl:
                    tp = Path(tpl)
                    if tp.is_dir():
                        for f in tp.iterdir():
                            if f.is_file() and f.suffix.lower() in (".py", ".md", ".txt", ".json", ".toml"):
                                dst = d / f.name
                                if not dst.exists():                       # 不覆盖用户已有文件
                                    dst.write_bytes(f.read_bytes())
                                    created["copied"].append(f.name)
                marker.write_text(json.dumps(created, ensure_ascii=False), "utf-8")
                return dict(ok=True, **created)
            def verify(r): return r.get("ok") and marker.exists() and (d / ".venv").exists()
            def undo(r):
                if not r.get("ok"):
                    return
                if not marker.exists():
                    return                                            # 标记没了=不是我们建的，不动
                try:
                    rec = json.loads(marker.read_text("utf-8"))
                except Exception:
                    rec = {}
                for name in rec.get("copied", []):
                    f = d / name
                    if f.exists():
                        f.unlink()
                if (d / ".venv").exists():
                    shutil.rmtree(d / ".venv", ignore_errors=True)
                marker.unlink(missing_ok=True)
            acts.append(Action("homework_prep", f"给 {d.name} 准备运行环境", "safe", "full", relief=0.5, blast_items=1,
                               reason="编号作业目录还没有 venv（创建我们自己的 .venv，可整份撤销）",
                               dry_run=dry, run=run, verify=verify, undo=undo,
                               done_text=lambda xs, d=d: f"给 {d.name} 建好了 .venv 运行环境（依赖装没装看有没有 requirements.txt，可撤销）",
                               done_short=lambda xs, d=d: f"给 {d.name} 备好环境"))
        return acts
    return Scenario("homework_env_prep", detect, propose)
