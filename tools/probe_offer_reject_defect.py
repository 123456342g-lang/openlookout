"""探针（缺陷已修，留作证据）：点「不用」之后，offers.jsonl 里到底有没有留下「已结论」？

发现的缺陷（已由 live.py 的 on_choice 修复 + 回归测试钉住）：
  旧on_choice 对 i!=0 只调 record_outcome（写 outcomes.jsonl），
  **不调** record_offer_result（写 offers.jsonl）。
  而 live.tick 判断「这条提议是不是已经有结论」用的是 offer_status(id)，
  它**只读 offers.jsonl**（live.py:603）。
  => 用户点了「不用」，offers.jsonl 里只有一行 shown，
     SETTLED_OFFER_STATES 里的 "rejected" 根本不会出现，
     窗口一重启（热更新就会重启）同一条提议又被摆出来问一遍。

跑法：
  "D:\\python3.11\\python.exe" tools\\probe_offer_reject_defect.py
  修好之后应打印「无缺陷」。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="ol_reject_probe_")).resolve()
os.environ["SPRITE_HOME"] = str(HOME)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "openlookout"))

from sprite.proactive import perceive

assert str(Path(perceive.DIR).resolve()).startswith(str(HOME)), "隔离失败，拒绝碰真实账本"

from sprite.proactive import help as helpmod, live

DIR = HOME / "perceive"
DIR.mkdir(parents=True, exist_ok=True)
live.DIR, live.OUTCOMES = DIR, DIR / "outcomes.jsonl"
helpmod.DIR, helpmod.OFFER = DIR, DIR / "offer.json"
helpmod.OFFER_LOG = DIR / "offers.jsonl"

offer = dict(id="probe-1", t=time.time(), text="C盘快满了，要我清一下吗？",
             topic="C盘", kind="offer", confidence=0.9,
             options=list(helpmod.OFFER_OPTIONS))
helpmod.publish(offer)
helpmod.record(dict(offer, result="shown"))


def _results():
    p = DIR / "offers.jsonl"
    return [json.loads(x)["result"] for x in p.read_text("utf-8").splitlines() if x.strip()]


print("offers.jsonl 初始:", _results())

# 只调 record_outcome（=旧 on_choice 的拒绝分支做的事）
live.record_outcome(offer, "rejected", options=offer["options"], choice_index=1, choice="不用")
print("只写 outcomes.jsonl 之后 offers.jsonl:", _results())
print(f"offer_status('probe-1') = {live.offer_status('probe-1')!r}")
print(f"  -> 会被当成没结论、重新问一遍吗 = "
      f"{live.offer_status('probe-1') not in live.SETTLED_OFFER_STATES}")

# 修复后的行为：拒绝也写 offers.jsonl
live.record_offer_result(offer, "rejected", choice="不用", choice_index=1)
st = live.offer_status("probe-1")
print()
print("修复后（拒绝也写 offers.jsonl）:", _results())
print(f"offer_status('probe-1') = {st!r}  已结论 = {st in live.SETTLED_OFFER_STATES}")
print()
print(">>> 无缺陷" if st in live.SETTLED_OFFER_STATES else ">>> 缺陷仍在")