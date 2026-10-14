"""跨轮次的记忆摘要：他接受过什么、拒绝过什么——作为每轮 STEP 的附证。

为什么单独一层：GUIDE.md（长期画像）模型可以用 read_guide 自己读，不必每轮塞进去；
但“他刚拒绝过哪个提议”这种**近期证据**如果每轮不给，模型很容易换一身说法再提一遍——
愿景里“用户反馈只作权衡”就落了空。这里只输出很短几行（token 成本近零），
按“结果”统计，不认场景：陪读、修电脑、整理桌面、写报告用的是同一套账。

数据源（issue #15 现状证据 5）：事实线读 ``perceive/outcomes.jsonl`` 的
``outcome == accepted / rejected`` 行。同意门之后 offers.jsonl 里
``accepted/dismissed`` 生产 0 行——真实结果只落 outcomes，继续读 offers 会让
【记忆】事实线恒空（被拒 topic 永远读不出来）。``responded``（用户打字）语义
不同于明确接受，这里不并入 accepted。
"""
from __future__ import annotations

import json, time
from pathlib import Path

RECENT_S = 7 * 86400          # 只看最近 7 天的结果
MAX_ITEMS = 4                 # 每边最多列几条，别把提示词撑爆
MIN_COUNT = 2                 # 同一话题至少出现这么多次才值得说（防止一次手滑就拉黑）


def _rows(path: Path) -> list[dict]:
    if not path.exists(): return []
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try: out.append(json.loads(raw))
        except ValueError: pass
    return out


def brief(home: Path, now: float | None = None) -> str:
    """一行代价的文本：接受过的 topic、拒绝过的 topic（含原话，方便模型避开）。

    读 outcomes.jsonl（一行一次开口的最终结果）：accepted 计「接受过」，
    rejected 计「拒绝过」且同 topic 需 ≥ MIN_COUNT 次才输出（一次手滑不拉黑）。
    没有数据 / 全部超出 7 天窗口 / 拒绝不足 MIN_COUNT 时返回空串——宁可安静。

    两侧门槛**有意不对称**（审查 P2-6 确认保留旧口径，不是漏写）：
    accepted 不设 MIN_COUNT——用户明确接住过一次的话题就值得记住，错记一条
    「他接受过」的代价只是少打扰；rejected 要 ≥ MIN_COUNT——把一次手滑/误点
    记成「别再提」会让模型永久绕开一个他其实可能要的话题，代价不对称。
    """
    now = now if now is not None else time.time()
    outcomes = Path(home) / "perceive" / "outcomes.jsonl"
    acc, rej = {}, {}
    for r in _rows(outcomes):
        t = r.get("t")
        if not isinstance(t, (int, float)) or isinstance(t, bool): continue
        if now - t > RECENT_S: continue
        outcome, topic = r.get("outcome"), (r.get("topic") or "").strip()
        if not topic: continue
        # accepted 有意不加 MIN_COUNT（见 docstring 的不对称说明，P2-6）
        if outcome == "accepted" and topic: acc[topic] = acc.get(topic, 0) + 1
        if outcome == "rejected" and topic:
            e = rej.setdefault(topic, dict(n=0, text=""))
            e["n"] += 1; e["text"] = e["text"] or str(r.get("text", ""))[:40]
    if not acc and not rej: return ""
    parts = []
    if acc: parts.append("接受过：" + "、".join(list(acc)[:MAX_ITEMS]))
    rej_items = [f"{t}（{v['text']}）" if v["text"] else t for t, v in list(rej.items())[:MAX_ITEMS] if v["n"] >= MIN_COUNT]
    if rej_items: parts.append("拒绝过、别换说法再提：" + "；".join(rej_items))
    if not parts: return ""
    return "【记忆】最近的反馈：" + "；".join(parts) + "。"
