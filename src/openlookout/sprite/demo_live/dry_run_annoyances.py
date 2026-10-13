"""干跑：在真实电脑上“只调查、不动手”。打印它找到的候选和理解记录（也写入 home/understandings.jsonl）。
python -m sprite.demo_live.dry_run_annoyances [--watch 秒] [--home DIR]"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
from ..scenarios import annoyance as A
from ..investigate import Candidate
from .common import home_dir


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--watch", type=int, default=0, help="先观察这么多秒的黑窗启动，再判断"); ap.add_argument("--home"); a = ap.parse_args(argv)
    home = Path(a.home) if a.home else home_dir(); home.mkdir(parents=True, exist_ok=True)
    sc, kit = A.build(home, live=False, log=lambda *x: print(*x, flush=True))
    pk, inv = kit["popup"], kit["inv"]; pk.obs.start()
    t_end = time.time() + a.watch
    while time.time() < t_end: time.sleep(5)
    print("== 计划任务审计（不依赖是否已观察到弹窗；只看“会弹窗且没藏起来”的非系统任务）==", flush=True)
    for t in pk.tasks(fresh=True):
        pi = A.parse_task(t.xml)
        if pi["n_exec"] != 1 or A.windowless(pi["command"], pi["args"]) or not pi["enabled"]: continue
        c = Candidate("task_popup", "task:" + t.path, f"计划任务 {t.path}", dict(audit=True), dict(path=t.path)); u = inv.investigate(c, None, force=True)
        print("-", u.line()); [print("    ·", e) for e in u.evidence]
        if u.act: print("    → 干跑：会把它的动作包成 conhost --headless（原 XML 存档、可还原），然后真跑一次校验")
    print("== 实际观察到的反复可见窗口 + 进程调查 ==", flush=True)
    sc.plans.clear(); probs = sc.detect(None)
    print(f"可行动问题 {len(probs)} 个；记录文件：{inv.file}")
    for p in probs: print("*", p.evidence)
    print("-- 全部调查过的候选 --")
    for k, (ts, u) in inv.cache.items(): print("-", u.line())


if __name__ == "__main__": main()