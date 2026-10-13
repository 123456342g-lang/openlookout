"""用户反馈：用户随时可以对小精灵说话（“不对，我在写论文”“别管这个”“你现在在做什么？”）。
- 每条写入 perceive/feedback.jsonl，并在 activity.log 留一行，方便事后核对。
- 理解层下一次判断时把最近的反馈当作用户的说明（比截图猜测更可靠），并立刻重新判断一次。
- 问句（“在做什么”）不记为纠正，直接用当前判断回答。
"""
from __future__ import annotations
import json, time
from datetime import datetime

from .perceive import DIR

FB_LOG = DIR / "feedback.jsonl"
ACT_LOG = DIR / "activity.log"
MAX_NOTES = 5
QUESTION_MARKS = ("?", "？", "在做什么", "在干嘛", "在干啥", "在做啥")


def feedback_kind(text: str) -> str:
    """把原话标成决策用途；原文始终保留，标签只帮助模型排序。"""
    value = text.strip()
    if is_question(value):
        return "question"
    if any(mark in value for mark in ("不对", "不是", "你误会", "我在", "别管", "不要再", "不用提")):
        return "correction"
    if any(mark in value for mark in ("以后", "我喜欢", "我更想", "我习惯", "偏好", "希望你")):
        return "preference"
    return "outcome"


def add_feedback(text: str, about: str) -> dict:
    value = text.strip()
    row = dict(t=time.time(), time=datetime.now().isoformat(timespec="seconds"), text=value,
               kind=feedback_kind(value), about=about or "")
    DIR.mkdir(parents=True, exist_ok=True)
    with FB_LOG.open("a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with ACT_LOG.open("a", encoding="utf-8") as f: f.write(f"{datetime.now():%H:%M:%S} 用户说：{row['text']}\n")
    return row


def recent_feedback(n: int = MAX_NOTES) -> list[dict]:
    if not FB_LOG.exists(): return []
    rows = []
    for line in FB_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        try: rows.append(json.loads(line))
        except ValueError: pass
    return rows[-n:]


def feedback_stamp() -> int:
    """文件大小变了就说明有新反馈。"""
    return FB_LOG.stat().st_size if FB_LOG.exists() else 0


def is_question(text: str) -> bool:
    return any(m in text for m in QUESTION_MARKS)
