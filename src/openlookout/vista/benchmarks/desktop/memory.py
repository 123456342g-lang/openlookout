"""跨轮次的记忆摘要：他接受过什么、拒绝过什么——作为每轮 STEP 的附证。

为什么单独一层：GUIDE.md（长期画像）模型可以用 read_guide 自己读，不必每轮塞进去；
但“他刚拒绝过哪个提议”这种**近期证据**如果每轮不给，模型很容易换一身说法再提一遍——
愿景里“用户反馈只作权衡”就落了空。这里只输出很短几行（token 成本近零），
按“结果”统计，不认场景：陪读、修电脑、整理桌面、写报告用的是同一套账。
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
    """一行代价的文本：接受过的 topic、拒绝过的 topic（含他的原话，方便模型避开）。"""
    now = now if now is not None else time.time()
    offers = Path(home) / "perceive" / "offers.jsonl"
    acc, rej = {}, {}
    for r in _rows(offers):
        if now - r.get("t", 0) > RECENT_S: continue
        res, topic = r.get("result"), (r.get("topic") or "").strip()
        if res == "accepted" and topic: acc[topic] = acc.get(topic, 0) + 1
        if res == "dismissed" and topic:
            e = rej.setdefault(topic, dict(n=0, text=""))
            e["n"] += 1; e["text"] = e["text"] or str(r.get("text", ""))[:40]
    if not acc and not rej: return ""
    parts = []
    if acc: parts.append("接受过：" + "、".join(list(acc)[:MAX_ITEMS]))
    rej_items = [f"{t}（{v['text']}）" if v["text"] else t for t, v in list(rej.items())[:MAX_ITEMS] if v["n"] >= MIN_COUNT]
    if rej_items: parts.append("拒绝过、别换说法再提：" + "；".join(rej_items))
    return "【记忆】最近的反馈：" + "；".join(parts) + "。"
