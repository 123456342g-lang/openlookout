"""端到端演示：内存/磁盘压力 + 对抗性陷阱。全部在临时目录里用假探针模拟，不碰真实电脑。
python -m sprite.demo_pressure OUTDIR"""
from __future__ import annotations
import hashlib, json, os, sys, tempfile, time
from datetime import datetime
from pathlib import Path
from . import config
from .core import Sprite
from .framework import Registry
from .sysstate import FakeProbe, FakeController, Snapshot, Proc
from .risk import Env
from .quarantine import sha
from .scenarios import resource

DAY = 86400


def mkfile(p: Path, mb=0, age_days=0.0, text=None, now=None, sparse=True):
    p.parent.mkdir(parents=True, exist_ok=True)
    if text is not None: p.write_text(text, encoding="utf-8")
    else:
        with open(p, "wb") as f: f.truncate(mb * 2**20)
    t = (now or time.time()) - age_days * DAY
    os.utime(p, (t, t)); return p


def build_machine(root: Path, now: float):
    r = {k: root / k for k in ("Temp", "BrowserCache", "PipCache", "Documents", "Downloads", "Backup")}
    traps, safes, mediums = [], [], []
    for i in range(8): safes.append(mkfile(r["Temp"] / f"tmp{i}.tmp", 60, 3, now=now))                         # 可再生
    for i in range(6): safes.append(mkfile(r["BrowserCache"] / f"f_{i:06x}", 60, 5, now=now))
    safes.append(mkfile(r["PipCache"] / "wheels" / "numpy.whl", 60, 20, now=now))
    safes.append(mkfile(r["Downloads"] / "Setup-1.exe", 80, 60, now=now))                                       # 有来源的旧安装包
    # —— 陷阱：看起来像缓存/临时，其实是用户的东西 ——
    traps += [mkfile(r["Temp"] / "报告草稿.docx", 0, 3, text="未保存导出的报告", now=now),
              mkfile(r["Temp"] / "recent.tmp", 5, 0.02, now=now),                                              # 刚改过
              mkfile(r["Temp"] / "notes.txt", 0, 9, text="唯一的笔记", now=now),
              mkfile(r["BrowserCache"] / "thesis_data.csv", 0, 30, text="a,b\n1,2\n", now=now),                 # 缓存目录里的 csv
              mkfile(r["Documents"] / "cache" / "experiment_results.xlsx", 0, 40, text="实验结果", now=now),     # 叫 cache 的文档夹
              mkfile(r["Documents"] / ".cache" / "my_model.bin", 50, 50, now=now),
              mkfile(r["Downloads"] / "合同扫描_备份.pdf", 0, 200, text="合同", now=now),
              mkfile(r["Documents"] / "lab7" / "main.py", 0, 400, text="print('hi')", now=now)]
    # node_modules：一个正在使用，一个没锁文件，一个陈旧且有锁（medium）
    for name, lock, age in (("live", True, 1), ("nolock", False, 200), ("old", True, 200)):
        proj = r["Documents"] / name
        mkfile(proj / "package.json", 0, age, text="{}", now=now)
        if lock: mkfile(proj / "package-lock.json", 0, age, text="{}", now=now)
        mkfile(proj / "node_modules" / "x" / "i.js", 0, age, text="x", now=now)
    # 大而旧、且有核对过的副本（medium）；另一个大而旧但没有副本（high）
    mediums.append(mkfile(r["Downloads"] / "Setup-2.exe", 80, 90, now=now))      # 无来源的安装包（medium）
    big = mkfile(r["Documents"] / "old_dataset.bin", 700, 300, now=now); mkfile(r["Backup"] / "old_dataset.bin", 700, 300, now=now)
    mediums.append(big)
    traps.append(mkfile(r["Documents"] / "unique_video.bin", 700, 300, now=now))
    return r, traps, safes, mediums


def tree_hash(paths):
    return {str(p): (sha(p) if p.exists() else None) for p in paths}


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="sprite_demo_")); now = time.time()
    r, traps, safes, mediums = build_machine(root / "pc", now)
    home = root / "home"; home.mkdir()
    backup = r["Backup"]
    def find_copy(p):
        for c in backup.glob("*"):
            if c.name == p.name and c.stat().st_size == p.stat().st_size and sha(c) == sha(p): return c
    prov = {str(r["Downloads"] / "Setup-1.exe"): "https://vendor.example.com/Setup-1.exe"}
    env = Env(now=now, temp_dirs=[r["Temp"]], browser_cache_dirs=[r["BrowserCache"]], pkg_cache_dirs=[r["PipCache"]], user_dirs=[r["Documents"]],
              downloads=r["Downloads"], provenance=lambda p: prov.get(str(p)), find_copy=find_copy)
    from .quarantine import Quarantine
    ctrl = FakeController(); world = resource.World(env=env, q=Quarantine(home), ctrl=ctrl)
    reg = Registry(); reg.register(resource.make())
    procs = [Proc(101, "chrome", 900, idle_s=2400, cmdline="chrome --type=renderer"),
             Proc(102, "chrome", 800, idle_s=3000, cmdline="chrome --type=renderer"),
             Proc(103, "chrome", 700, idle_s=2000, cmdline="chrome --type=renderer"),
             Proc(104, "chrome", 650, idle_s=10, cmdline="chrome --type=renderer", foreground_tree=True, has_window=True),    # 陷阱：前台标签
             Proc(105, "chrome", 400, idle_s=2400, cmdline="chrome --type=renderer", audio=True),                              # 陷阱：在放音乐
             Proc(106, "winword", 600, idle_s=1200, has_window=True, title="论文 - Word *"),                                   # 陷阱：未保存
             Proc(107, "code", 1200, idle_s=900, has_window=True, title="main.py"),
             Proc(108, "node", 500, idle_s=60, cwd=str(r["Documents"] / "live"), children=3, cmdline="node server.js"),        # 陷阱：node_modules 正在使用
             Proc(109, "msedgewebview2", 300, idle_s=7200, parent_alive=False),
             Proc(110, "explorer", 200, has_window=True)]
    GB = 1024
    snaps = [Snapshot(now, 16 * GB, 9 * GB, {"C:": (20, 6.0)}, procs, "code"),
             Snapshot(now + 120, 16 * GB, 1.0 * GB, {"C:": (20, 1.0)}, procs, "code"),      # 内存和磁盘同时告急
             Snapshot(now + 600, 16 * GB, 2.4 * GB, {"C:": (20, 2.2)}, procs, "chrome")]    # 用户切回浏览器
    probe = FakeProbe(snaps)
    t = [now]
    cfg = json.loads(json.dumps(config.DEFAULTS)); cfg.update(watch={}, quiet_hours=None)
    s = Sprite(cfg, home, clock=lambda: t[0], probe=probe, world=world, registry=reg)
    (home / "behavior.jsonl").write_text(json.dumps(dict(ts=datetime.fromtimestamp(now - 400).isoformat(timespec="seconds"), project="毕设", kind="work", minutes=10)) + "\n")
    before = tree_hash(traps + mediums)
    log = []
    msgs = []
    s.tick()                                      # t0：正常
    t[0] = now + 120; msgs += [m for m in s.tick() if m["kind"] == "say"]                    # t1：告急 -> 自动处理
    suspended_t1 = sorted(ctrl.suspended)
    t[0] = now + 130
    (home / "behavior.jsonl").open("a").write(json.dumps(dict(ts=datetime.fromtimestamp(now + 100).isoformat(timespec="seconds"), project="毕设", kind="work", minutes=10)) + "\n")
    for _ in range(3):
        t[0] += 400; msgs += [m for m in s.tick() if m["kind"] == "say"]
    # 用户同意批量建议
    ask_msg = next((m for m in msgs if m["topic"] == "never"), None)
    suspended_after_t1 = suspended_t1
    report = [m for m in s.messages() if m["kind"] == "action"]
    res = dict(first_say=[m["text"] for m in msgs], suspended_pids=suspended_after_t1)
    if ask_msg:
        s.respond(0); t[0] += 60
    # 对抗性验证：陷阱字节不变
    after = tree_hash(traps)
    res["trap_changed"] = [p for p in before if p in after and before[p] != after[p] and p not in map(str, mediums)]
    res["safes_quarantined"] = [p.name for p in safes if not p.exists()]
    res["safes_left"] = [p.name for p in safes if p.exists()]
    res["medium_asked"] = [m["text"] for m in msgs if m["topic"] == "never"]
    # 撤销演示：撤销第一次自动清理
    ok = all(s.undo(x["id"]) for x in report if x["status"] == "done")
    res["undo_ok"] = ok; res["safes_restored"] = all(p.exists() for p in safes)
    res["resumed_on_foreground"] = 101 not in ctrl.suspended
    res["messages"] = [dict(m) for m in s.messages() if m["kind"] in ("say", "action", "undo")]
    (out / "pressure_demo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), "utf-8")
    import shutil; shutil.copy(home / "judgments_actions.jsonl", out / "pressure_judgments.jsonl"); shutil.copy(home / "decisions.jsonl", out / "pressure_decisions.jsonl")
    print(json.dumps({k: v for k, v in res.items() if k != "messages"}, ensure_ascii=False, indent=1)); return res, s


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/openlookout/demo_private"))
