# -*- coding: utf-8 -*-
"""PC: run FakeNovel e2e into sprite_home, write messages, start GUI live."""
from __future__ import annotations
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"E:\OpenLookout")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("TEMP", r"E:\OpenLookout\tmp")
os.environ.setdefault("TMP", r"E:\OpenLookout\tmp")
Path(r"E:\OpenLookout\tmp").mkdir(parents=True, exist_ok=True)

home = Path(r"E:\OpenLookout\sprite_home")
home.mkdir(parents=True, exist_ok=True)
for n in ("STOP_DEMO", "KILL"):
    (home / n).unlink(missing_ok=True)

# kill old sprite pythons
try:
    import psutil
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            name = (p.info["name"] or "").lower()
        except Exception:
            continue
        if "sprite" in cl.lower() and "python" in name:
            print("kill", p.info["pid"], cl[:160])
            try:
                p.terminate()
            except Exception:
                pass
    time.sleep(1.0)
except Exception as e:
    print("psutil skip", e)

dc_path = home / "demo_live.json"
dc = json.loads(dc_path.read_text(encoding="utf-8")) if dc_path.exists() else {}
dc.update(dict(annoyance_apply=True, network_apply=True, stalemate_apply=True, novel_from_env=True))
dc_path.write_text(json.dumps(dc, ensure_ascii=False, indent=1), encoding="utf-8")

from sprite.investigate import Candidate, Understanding, InvestigatorRegistry, Investigator, investigator_scenario
from sprite.novel import FakeNovelClient, NovelUnderstander
from sprite.framework import Engine, Registry

now = time.time()
# seed observation events (generic traces, not network-first)
rows = [
    {"ts": datetime.fromtimestamp(now - 400, tz=timezone.utc).isoformat(),
     "type": "focus", "app": "WeirdCAD", "title": "参数面板 ???", "dur_s": 220},
    {"ts": datetime.fromtimestamp(now - 30, tz=timezone.utc).isoformat(),
     "type": "browser_error", "url": "http://172.16.170.169/", "error": "ERR_EMPTY_RESPONSE"},
]
(home / "events.jsonl").write_text(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

(eh := home / "eh_final").mkdir(exist_ok=True)
client = FakeNovelClient(dict(
    what="陌生 CAD 久停，且局域网页 ERR_EMPTY_RESPONSE",
    why="不定死为网络类；先可逆记下证据与理解",
    state="unknown", confidence=0.82, act=True,
    candidate_actions=[dict(kind="archive_note", args={}, reason="记下待跟进", risk="safe", reversible="full")],
))
novel = NovelUnderstander(home, clock=lambda: now, client=client, enabled=True, prefer_novel=True)
ireg = InvestigatorRegistry()

def disc(w):
    return [Candidate("anomaly", "a:ui1", "合成 UI 异常（久停+浏览失败）",
                      signals=dict(need=1.0, severity=0.55, unit="处"), ctx=dict(home=str(home)))]

def gather(c, facts, world, view):
    facts["home"] = str(home); facts["what"] = "久停+浏览空响应"
    return ["dwell WeirdCAD 220s", "browser_error ERR_EMPTY_RESPONSE @172.16.170.169"]

ireg.discoverer("anomaly", disc)
ireg.gatherer("anomaly", lambda c: c.kind == "anomaly", gather)
ireg.judge("anomaly", lambda c, f: Understanding(
    c.key, c.kind, c.title, state="unknown", confidence=0.15, act=False, why="本地不定性"))
ireg.responder("anomaly", lambda c, u, w: [], lambda c, w: 1.0)

class V:
    def now(self): return now
    def self_pid(self): return -1
    def procs(self): return {}
    def open_files(self, pid): return []
    def newest_mtime(self, *a, **k): return None
    def git_root(self, path): return None
    def git_dirty(self, root): return None
    def read_head(self, path, n=4000): return ""
    def exists(self, path): return Path(path).exists()

inv = Investigator(ireg, V(), home, lambda: now, log=print, novel=novel, prefer_novel=True)
sc = investigator_scenario(ireg, inv, live=True, min_conf=0.70, log=print, name="final_demo")
reg = Registry(); reg.register(sc)

class World:
    home = home

outs = Engine(reg, eh, clock=lambda: now).step(World())
acted = [a for o in outs for a in o.acted]
print("ACTED", [a.kind for a in acted], "novel_calls", len(client.calls))

ts = datetime.now().isoformat(timespec="seconds")
msgs = [
    dict(ts=ts, kind="say", text="看到你卡在 WeirdCAD，还开了个 ERR_EMPTY_RESPONSE 的页…我先理解一下。",
         options=[], status="shown"),
]
for o in outs:
    if o.acted:
        msgs.append(dict(
            ts=ts, kind="action", text=o.text_short or o.text_done, detail=o.text_done,
            action_id=o.acted[0].id, options=["撤销", "详情"], status="done",
            kinds=[x.kind for x in o.acted],
        ))
# append to messages.jsonl (keep history)
with (home / "messages.jsonl").open("a", encoding="utf-8") as f:
    for m in msgs:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")
print("messages written", len(msgs))
print("understandings", (home / "understandings.jsonl").exists())
# stamp for parent
(Path(r"E:\OpenLookout\FINAL_VISIBLE.json")).write_text(
    json.dumps(dict(ok=bool(acted), acted=[a.kind for a in acted], msgs=msgs, novel_calls=len(client.calls)),
               ensure_ascii=False, indent=2), encoding="utf-8")

# start GUI live in background via pythonw
pyw = Path(r"D:\python3.11\pythonw.exe")
py = Path(r"D:\python3.11\python.exe")
exe = str(pyw if pyw.exists() else py)
log = home / "demo_live.log"
# touch log
with log.open("a", encoding="utf-8") as f:
    f.write(time.strftime("%H:%M:%S ") + "pc_run_visible launching live --live\n")
creation = 0x00000008  # DETACHED_PROCESS
# Use CREATE_NEW_PROCESS_GROUP | DETACHED
flags = 0x00000200 | 0x00000008
env = os.environ.copy()
env["SPRITE_HOME"] = str(home)
env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
proc = subprocess.Popen(
    [exe, "-m", "sprite.demo_live.live", "--live"],
    cwd=str(ROOT),
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=flags,
)
print("launched pid", proc.pid, "exe", exe)
(Path(r"E:\OpenLookout\FINAL_VISIBLE.json")).write_text(
    json.dumps(dict(ok=bool(acted), acted=[a.kind for a in acted], msgs=msgs,
                    novel_calls=len(client.calls), live_pid=proc.pid),
               ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
