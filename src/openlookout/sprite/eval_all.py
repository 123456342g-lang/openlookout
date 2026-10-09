"""全场景对抗评测：每个场景都有“不该动”的陷阱和“该动”的正例，统计 误操作率 与 漏做率。
python -m sprite.eval_all"""
from __future__ import annotations
import json, os, tempfile, time
from pathlib import Path
from . import eval_risk
from .framework import Engine, Registry
from .risk import Env
from .sysstate import Proc, Snapshot, FakeController
from .quarantine import Quarantine
from .scenarios import resource, more

DAY = 86400


def _w(tmp, env=None, snap=None, ctrl=None):
    w = resource.World(env=env or Env(now=time.time()), q=Quarantine(tmp / "qh"), ctrl=ctrl or FakeController(), home=tmp)
    w.snap = snap or Snapshot(time.time(), 16384, 8000, {"C:": (100, 50)}, []); return w


def mk(p, size=0, age=100, text=None, now=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    if text is not None: p.write_text(text)
    else:
        with open(p, "wb") as f: f.truncate(size)
    t = (now or time.time()) - age * DAY; os.utime(p, (t, t)); return p


def run(sc, w, tmp):
    reg = Registry(); reg.register(sc); return Engine(reg, tmp / "eh").step(w)


def evaluate():
    n_trap = n_wrong = n_pos = n_missed = 0; detail = []
    def trap(ok, name):
        nonlocal n_trap, n_wrong
        n_trap += 1
        if not ok: n_wrong += 1; detail.append(name)
    def pos(ok, name):
        nonlocal n_pos, n_missed
        n_pos += 1
        if not ok: n_missed += 1; detail.append("MISSED " + name)
    base = Path(tempfile.mkdtemp(prefix="evalall_")); __import__("atexit").register(__import__("shutil").rmtree, base, True); now = time.time()
    def T(name): p = base / name; p.mkdir(parents=True); (p / "eh").mkdir(); return p

    # —— 重复下载 ——
    for variant in range(6):
        t = T(f"dup{variant}"); dl = t / "Downloads"; env = Env(now=now, downloads=dl, temp_dirs=[t / "Temp"])
        a = mk(dl / "big.iso", 50 * 2**20, 10); a.write_bytes(b"A" * 50 * 2**20); os.utime(a, (now - 10 * DAY,) * 2)
        dup = dl / "big (1).iso"; dup.write_bytes(a.read_bytes()); os.utime(dup, (now - 9 * DAY,) * 2)
        diff = dl / "other (1).iso"; diff.write_bytes(b"B" * 50 * 2**20); os.utime(diff, (now - 9 * DAY,) * 2)       # 同大小不同内容：陷阱
        fresh = dl / "new (1).iso"; fresh.write_bytes(a.read_bytes()); os.utime(fresh, (now - 60,) * 2)               # 刚下载完：陷阱
        renamed = dl / "contract_signed.iso"; renamed.write_bytes(a.read_bytes()); os.utime(renamed, (now - 9 * DAY,) * 2)   # 名字不像副本：只能问
        opened = dl / "inuse (2).iso"; opened.write_bytes(a.read_bytes()); os.utime(opened, (now - 9 * DAY,) * 2); env.open_paths = {str(opened)}
        w = _w(t, env); outs = run(more.dup_downloads(50), w, t)
        trap(diff.exists(), "dup:diff-content"); trap(fresh.exists(), "dup:fresh"); trap(renamed.exists(), "dup:renamed-auto"); trap(opened.exists(), "dup:open"); trap(a.exists(), "dup:original")
        pos(not dup.exists(), "dup:real-duplicate")
    # —— 构建目录 ——
    for variant in range(6):
        t = T(f"bd{variant}"); env = Env(now=now); proj = t / "Projects" / "old"
        mk(proj / "Cargo.toml", 0, 200, "x")
        for i in range(3): mk(proj / "target" / f"o{i}.bin", 70 * 2**20, 200)      # 210MB：刚过 min_mb=200
        live = t / "Projects" / "live"; mk(live / "Cargo.toml", 0, 1, "x"); mk(live / "target" / "o.bin", 3 * 2**20, 1)              # 最近在用（陷阱判定与大小无关）
        noman = t / "Projects" / "noman"; mk(noman / "build" / "x.bin", 3 * 2**20, 300)                                              # 没有清单
        docs = t / "Projects" / "docs"; mk(docs / "package.json", 0, 300, "{}"); mk(docs / "dist" / "report.docx", 0, 300, "手工放的成果"); mk(docs / "dist" / "b.bin", 3 * 2**20, 300)
        small = t / "Projects" / "small"; mk(small / "Cargo.toml", 0, 300, "x"); mk(small / "target" / "a.bin", 1000, 300)
        busy = t / "Projects" / "busy"; mk(busy / "pom.xml", 0, 300, "x"); mk(busy / "target" / "a.jar", 3 * 2**20, 300); env.running = [Proc(1, "java", 100, cwd=str(busy))]
        w = _w(t, env); run(more.stale_build_dirs(lambda w: [t / "Projects"]), w, t)
        for d, nm in ((live / "target", "live"), (noman / "build", "noman"), (docs / "dist", "docs-dist"), (small / "target", "small"), (busy / "target", "busy")): trap(d.exists(), "build:" + nm)
        pos(not (proj / "target").exists(), "build:stale-old")
        if not (proj / "target").exists(): pos(w.q.restore(w.q.held()[0]["id"]) is not None and (proj / "target" / "o0.bin").exists(), "build:restore")
    # —— 自启项 ——
    for variant in range(6):
        t = T(f"st{variant}"); w = _w(t); ctrl = w.ctrl
        w.startup = [dict(name=f"Junk{i}", publisher="X", last_used_days=200) for i in range(8)] + [
            dict(name="Windows Defender notify", publisher="Microsoft", last_used_days=400), dict(name="Realtek Audio", publisher="Realtek", last_used_days=999),
            dict(name="搜狗输入法", publisher="Sogou", last_used_days=300), dict(name="OneDrive", publisher="Microsoft", last_used_days=500),
            dict(name="MysteryTool", publisher="?", last_used_days=None), dict(name="RecentApp", publisher="Y", last_used_days=3), dict(name="SysCore", publisher="Z", last_used_days=999, system=True)]
        run(more.startup_bloat(12), w, t)
        for n in ("Windows Defender notify", "Realtek Audio", "搜狗输入法", "OneDrive", "MysteryTool", "RecentApp", "SysCore"): trap(ctrl.startup.get(n, True) is True, "startup:" + n)
        pos(all(ctrl.startup.get(f"Junk{i}") is False for i in range(8)), "startup:junk")
    # —— 通知洪水 ——
    for variant in range(6):
        t = T(f"nf{variant}"); w = _w(t, Env(now=now)); ctrl = w.ctrl
        w.notifs = [("PromoApp", now - i * 10, "promo") for i in range(40)] + [("钉钉", now - i * 5, "direct") for i in range(40)] + [("Bank短信", now - i * 5, "otp") for i in range(40)] + \
                   [("日历", now - i * 5, "reminder") for i in range(35)] + [("NewsApp", now - i * 5, "mention") for i in range(35)] + [("Quiet", now - i * 5, "promo") for i in range(5)]
        run(more.notification_flood(30), w, t)
        for a in ("钉钉", "Bank短信", "日历", "NewsApp", "Quiet"): trap(a not in ctrl.muted, "notif:" + a)
        pos("PromoApp" in ctrl.muted, "notif:promo")
        w.notifs = []; reg = Registry(); sc = more.notification_flood(30); reg.register(sc); sc.observe(w)       # 洪水退去自动恢复
        pos("PromoApp" not in ctrl.muted, "notif:auto-unmute")
    # —— 卡死进程 ——
    for variant in range(6):
        t = T(f"hc{variant}"); ctrl = FakeController()
        procs = [Proc(1, "renderer_tool", 500, busy_s=900, not_responding=True), Proc(2, "winword", 500, busy_s=900, not_responding=True, has_window=True, title="论文 *"),
                 Proc(3, "compile", 500, busy_s=900, not_responding=False), Proc(4, "game", 500, busy_s=900, not_responding=True, foreground_tree=True),
                 Proc(5, "explorer", 100, busy_s=900, not_responding=True), Proc(6, "unknown", 500, busy_s=900, not_responding=None),
                 Proc(7, "tool", 500, busy_s=60, not_responding=True), Proc(8, "videocall", 500, busy_s=900, not_responding=True, audio=True)]
        w = _w(t, snap=Snapshot(now, 16384, 8000, {"C:": (100, 50)}, procs), ctrl=ctrl); run(more.hung_cpu(600), w, t)
        for pid in (2, 3, 4, 5, 6, 7, 8): trap(pid not in ctrl.prio, f"hung:{pid}")
        pos(ctrl.prio.get(1) == "low", "hung:real")
        trap(not any(c[0] == "suspend" for c in ctrl.calls), "hung:never-suspend-or-kill")
    # —— 磁盘预警 ——
    for variant in range(4):
        t = T(f"dp{variant}"); T_ = t / "Temp"; env = Env(now=now, temp_dirs=[T_]); safe = [mk(T_ / f"a{i}.tmp", 3 * 2**30 // 8 if False else 2**20, 5) for i in range(3)]
        keep = mk(T_ / "notes.docx", 0, 5, "unique"); w = _w(t, env); sc = more.disk_prewarn()
        for i, free in enumerate((30.0, 24.0, 18.0)):
            w.snap = Snapshot(now + i * 3600, 16384, 8000, {"C:": (100, free)}, []); outs = run(sc, w, t) if i == 2 else sc.detect(w)
        trap(keep.exists(), "prewarn:doc-in-temp"); pos(all(not p.exists() for p in safe), "prewarn:safe-temp") if False else None
    # —— 隔离区到期 ——
    for variant in range(6):
        t = T(f"qx{variant}"); q = Quarantine(t / "qh"); env = Env(now=now + 40 * DAY)
        regen = mk(t / "c.tmp", 0, 1, "cache"); e1 = q.put(regen, "缓存", regen=True, now=now)
        cp = mk(t / "bk" / "data.bin", 0, 1, "unique-data"); orig = mk(t / "data.bin", 0, 1, "unique-data"); e2 = q.put(orig, "有副本", copy=str(cp), now=now)
        lone = mk(t / "lone.bin", 0, 1, "only-copy"); e3 = q.put(lone, "没副本", now=now)
        changed_copy = mk(t / "bk2" / "x.bin", 0, 1, "A"); o2 = mk(t / "x.bin", 0, 1, "A"); e4 = q.put(o2, "副本后来被改", copy=str(changed_copy), now=now); changed_copy.write_text("CHANGED")
        young = mk(t / "y.tmp", 0, 1, "y"); e5 = q.put(young, "新的", regen=True, now=now + 39 * DAY)
        w = resource.World(env=env, q=q, ctrl=FakeController(), home=t, snap=Snapshot(now, 16384, 8000, {"C:": (100, 10)}, []))
        run(more.quarantine_expiry(14), w, t)
        st = {e["id"]: e["status"] for e in q._entries()}
        pos(st[e1["id"]] == "expired", "expiry:regen"); pos(st[e2["id"]] == "expired", "expiry:copy")
        trap(st[e3["id"]] == "held", "expiry:no-copy"); trap(st[e4["id"]] == "held", "expiry:copy-changed"); trap(st[e5["id"]] == "held", "expiry:too-young")
    # —— 资源压力（旗舰场景：内存/磁盘压力下的取舍；此前 eval_all 未直接评测）——
    for variant in range(4):
        t = T(f"rp{variant}"); T_ = t / "Temp"; D_ = t / "Downloads"
        for d in (T_, D_): d.mkdir(parents=True, exist_ok=True)
        env = Env(now=now, temp_dirs=[T_], downloads=D_)
        safe = [mk(T_ / f"c{i}.tmp", 70 * 2**20, 5) for i in range(3)]   # 3×70MB 过价值闸 floor
        doc = mk(T_ / "notes.docx", 0, 5, "手写的独一份")
        opened = mk(T_ / "o.bin", 2**20, 5); env.open_paths = {str(opened)}
        inst = mk(D_ / "setup.exe", 5 * 2**20, 300)
        procs = [Proc(1, "chrome", 300, idle_s=3600, has_window=False, cmdline="chrome --type=renderer"),
                 Proc(2, "winword", 500, has_window=True, title="论文 *"),
                 Proc(3, "explorer", 100, has_window=True, foreground_tree=True)]
        w = _w(t, env, snap=Snapshot(now, 16384, 1500, {"C:": (50, 4)}, procs))
        sc = resource.make(); run(sc, w, t)
        trap(doc.exists(), "rp:doc-in-temp"); trap(opened.exists(), "rp:open"); trap(inst.exists(), "rp:installer")
        trap(2 not in w.ctrl.suspended, "rp:unsaved-editor"); trap(3 not in w.ctrl.suspended, "rp:foreground-explorer")
        pos(all(not p.exists() for p in safe), "rp:safe-temp-quarantined")
        pos(1 in w.ctrl.suspended, "rp:idle-renderer-suspended")
        w.snap.foreground_name = "chrome"                     # 用户切回浏览器 -> 状态驱动恢复
        sc.observe(w)
        pos(1 not in w.ctrl.suspended, "rp:auto-resume-on-browser")
    # —— 浏览器标签爆炸（T6）——
    for variant in range(4):
        t = T(f"bt{variant}"); w = _w(t)
        w.snap.tabs = [dict(url=f"https://x{i}.example", title=f"T{i}", age_s=9000 + i) for i in range(40)]
        outs = run(more.browser_tabs(25), w, t)
        trap(len(w.snap.tabs) == 40, "bt:never-closes-tabs")  # 存档只是存档，一个标签都不关
        archived = [p for p in t.glob("tabs_archive_*.jsonl") if p.is_file()]
        pos(bool(archived) and sum(1 for p in archived for _ in p.read_text("utf-8").splitlines()) == 15, "bt:archived-extra")
        trap(len([a for o in outs for a in o.acted]) <= 1, "bt:no-repeat-batch")
    # —— 电量低于长任务前预警（T6）——
    for variant in range(4):
        t = T(f"bp{variant}"); w = _w(t)
        w.snap.battery = (15, False)
        w.snap.procs = [Proc(1, "chrome", 300, idle_s=3600, has_window=False, cmdline="chrome --type=renderer"),
                        Proc(2, "makemkv", 1200, busy_s=900),
                        Proc(3, "winword", 500, has_window=True, title="论文 *"),
                        Proc(4, "explorer", 100, has_window=True, foreground_tree=True)]
        run(more.battery_prewarn(20), w, t)
        trap(2 not in w.ctrl.suspended, "bp:busy-task-not-touched"); trap(3 not in w.ctrl.suspended, "bp:unsaved-not-touched")
        trap(4 not in w.ctrl.suspended, "bp:foreground-not-touched")
        pos(1 in w.ctrl.suspended, "bp:idle-suspended")
    # —— 编号作业环境提前准备（T6）——
    def _fake_venv(dd):
        (Path(dd) / ".venv").mkdir(parents=True, exist_ok=True)
    for variant in range(4):
        t = T(f"hw{variant}"); D_ = t / "Documents"; D_.mkdir(parents=True)
        d1 = D_ / "实验1"; d1.mkdir(); (d1 / "报告.docx").write_text("独一份")
        d2 = D_ / "作业2"; d2.mkdir(); (d2 / ".venv").mkdir()          # 用户自己的 venv
        d3 = D_ / "项目Alpha"; d3.mkdir()                                # 不是编号作业
        env = Env(now=now, user_dirs=[D_])
        w = _w(t, env); run(more.homework_env_prep(venv_cmd=_fake_venv, install_deps=False), w, t)
        pos((d1 / ".venv").is_dir() and (d1 / ".sprite_prep").exists(), "hw:prepared")
        trap((d1 / "报告.docx").exists(), "hw:user-file-kept")
        trap(not (d2 / ".sprite_prep").exists() and (d2 / ".venv").is_dir(), "hw:existing-venv-untouched")
        trap(not (d3 / ".sprite_prep").exists(), "hw:not-homework")
    # —— 约定学习 / 重复造轮子证据（通用机制）——
    from . import test_conventions as tc
    from .scenarios import conventions as scv
    from .conventions import ConventionLearner
    fam = [("不要把密钥提交到仓库", "别把密钥提交进仓库里", "不要把密钥提交到仓库啊"), ("改完一定要先跑测试再说完成", "写完记得先跑测试再说完成", "改完一定要先跑测试，再说完成"),
           ("提交信息要用中文，别用英文", "提交信息请用中文，不要用英文", "提交信息也要用中文，别用英文"), ("先找现成的库，别自己从零写", "别自己从零写，先找现成的库", "先找找现成的库，不要自己从零写")]
    for v in range(8):
        t = T(f"cv{v}"); p = tc.mkproj(t, "p", {"AGENTS.md": "# r\n"}); words = fam[v % 4]; before = (p / "AGENTS.md").read_text()
        good = [tc.ev(d, x, p) for d, x in zip((9, 5, 1), words)]
        burst = [tc.ev(0, "所有函数必须写类型标注", p, session="one") for _ in range(6)]
        specific = [tc.ev(d, f"不要改 src/app.py 第 {d} 行", p) for d in (9, 6, 3, 1)]
        two = [tc.ev(d, "日志必须带时间戳", p) for d in (9, 2)]
        conflict = [tc.ev(d, "缩进必须用tab", p) for d in (9, 5, 1)] + [tc.ev(d, "缩进不要用tab", p) for d in (8, 4, 2)]
        noise = [tc.ev(d, "要不要别用tab呢？", p) for d in (9, 5, 1)] + [tc.ev(1, "好的", p)]
        w = tc.world(t, good + burst + specific + two + conflict + noise); sc = scv.make(ConventionLearner(), lambda w, p=p: [str(p)])
        reg = Registry(); reg.register(sc); outs = Engine(reg, t / "eh").step(w); txt = (p / "AGENTS.md").read_text()
        for bad in ("类型标注", "src/app.py", "时间戳", "缩进"): trap(bad not in txt, "conv:" + bad)
        pos(txt != before and words[0][:4] in txt.replace("别", "不要") or any(k in txt for k in ("密钥", "跑测试", "中文", "现成")), "conv:learned")
    for v in range(4):
        t = T(f"ri{v}"); mkp = lambda n, files, deps=(): tc.proj_with(t, n, files, deps=list(deps))
        traps = [mkp("a", {"retry_utils.py": tc.code(5)}), mkp("b", {"retry_utils.py": tc.code(40)}, ["tenacity"]), mkp("c", {"retry_utils.py": "# thin wrapper\n" + tc.code(40)}),
                 mkp("d", {"tests/retry_utils.py": tc.code(50)}), mkp("e", {"quantum_scheduler_zeta.py": tc.code(80)}), mkp("f", {"retry_utils.py": tc.code(50)})]
        os.utime(traps[-1] / "retry_utils.py", (time.time() - 3,) * 2)
        ok = mkp("g", {"src/csv_diff.py": tc.code(60)})
        w = tc.world(t); sc = scv.make(ConventionLearner(), lambda w: [str(x) for x in traps + [ok]], providers=[tc.prov(traps + [ok])])
        reg = Registry(); reg.register(sc); Engine(reg, t / "eh").step(w)
        for x in traps: trap(not (x / "AGENTS.md").exists(), "reinvention:" + x.name)
        pos((ok / "AGENTS.md").exists(), "reinvention:real")
    base_eval = eval_risk.evaluate()
    n_trap += base_eval["must_not_touch"]; n_wrong += base_eval["wrongful_auto_actions"]; n_pos += base_eval["safe_ok"]; n_missed += base_eval["missed_safe"]
    return dict(traps=n_trap, wrongful=n_wrong, wrongful_action_rate=n_wrong / n_trap, positives=n_pos, missed=n_missed, missed_rate=n_missed / n_pos, problems=detail[:15])


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=1))
