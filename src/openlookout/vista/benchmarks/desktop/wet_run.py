"""真跑一次：真屏幕 + 真系统事实 → 真模型判断 → 过时机闸 → 落到 offer.json。

这是端到端的最后一米：不需要 Docker（那只是 Claude Code 的传输通道），
跑的是「看准时机」本身——模型看着真屏幕和真事实，决定此刻说不说话。

用法：
    python -m vista.benchmarks.desktop.wet_run            # 只看判断，不发布
    python -m vista.benchmarks.desktop.wet_run --publish  # 真落到 offer.json（会打扰你）
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("SPRITE_HOME", r"E:\OpenLookout\sprite_home"))
# .env 在仓库根：src/openlookout/vista/benchmarks/desktop/ 上溯5 层
ENV = Path(__file__).resolve().parents[5] / ".env"


def api_key() -> str:
    for line in ENV.read_text("utf-8", errors="replace").splitlines():
        if line.strip().startswith("SPRITE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("没有 SPRITE_API_KEY")


def ask(prompt: str, image_b64: str | None, *, max_tokens: int = 400) -> str:
    """问模型一次。端点/模型从 provider.json 读，key 只从 .env 读且不打印。

    实测坑：这个模型会先输出一段 thinking 再给正文，thinking 也吃 max_tokens；
    偶尔会把预算吃光导致正文为空。所以：留够预算，并且空结果会重试一次。
    """
    from sprite.proactive.provider import load_provider
    p = load_provider()
    for attempt in (max_tokens, max_tokens * 4):
        content = []
        if image_b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
        content.append({"type": "text", "text": prompt})
        body = {"model": p.model, "max_tokens": attempt,
                "messages": [{"role": "user", "content": content}]}
        req = urllib.request.Request(p.base_url + "/v1/messages", data=json.dumps(body).encode(),
                                     headers={"x-api-key": api_key(), "anthropic-version": "2023-06-01",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode())
        # thinking 块有时与正文重复，只取 text 块，thinking 仅在正文为空时兜底
        texts = [c.get("text") or "" for c in d.get("content", []) if c.get("type") == "text"]
        out = "".join(t for t in texts if t).strip()
        if not out:
            thinks = "".join(c.get("thinking") or "" for c in d.get("content", []) if c.get("type") == "thinking")
            out = thinks.strip()
        if out:
            return out
    return ""


PROMPT = (
    "这是用户电脑此刻的屏幕截图。下面是确定性测得的事实，不要重复推断：\n{facts}\n"
    "你是陪在用户身边的小精灵，看准时机主动帮忙。绝大多数时候应该安静（kind=quiet）。"
    "只有他明显需要、且你能具体帮上忙时才开口。\n"
    '只输出一个 JSON，不要别的：{{"kind":"quiet"|"companion"|"offer",'
    '"say":"一句自然口语的话，不超过30字","topic":"6字内标签","confidence":0到1}}\n'
    "说“用户”不行；不要像报告；拿不准就 quiet。"
)


def parse(text: str) -> dict | None:
    """从模型输出里挖出 JSON。

    实测这个模型经常把 JSON 包在 ```json ... ``` 里，也会前后带寒暄，
    所以不能只找裸 JSON——先把围栏剥掉，再逐个候选试。
    """
    if not text:
        return None
    t = text.strip()
    # 剥 markdown 围栏
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    for m in reversed(list(re.finditer(r"\{.*?\}", t, re.S))):
        blob = m.group(0)
        try:
            d = json.loads(blob)
            if isinstance(d, dict) and "kind" in d:
                return d
        except ValueError:
            # 括号不配对时（贪婪匹配可能吞掉尾巴），退一步用贪婪再试一次
            try:
                d = json.loads(re.search(r"\{.*\}", blob, re.S).group(0))
                if isinstance(d, dict) and "kind" in d:
                    return d
            except (ValueError, AttributeError):
                continue
    return None


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="真落到 offer.json（会在气泡里出现）")
    a = ap.parse_args(argv)

    from vista.benchmarks.desktop import systemfacts, watching
    from vista.benchmarks.desktop.brain import thumb
    from vista.benchmarks.desktop.session import screen_visual

    vis = screen_visual()
    th = thumb(vis)
    facts = []
    sf = systemfacts.SystemWatcher().observe()
    if line := sf.line():
        facts.append(line)
    else:
        facts.append("(系统正常，无告警)")
    w = watching.load(HOME).observe(th, "", idle_s=watching.idle_seconds())
    if line := w.line():
        facts.append(line)

    print(f"[事实] 截图 {len(vis.data)} 字节")
    for f in facts:
        print("      " + f)

    raw = ask(PROMPT.format(facts="\n".join(facts)), base64.b64encode(vis.data).decode())
    raw = (raw or "").strip()
    print(f"[模型] {raw[:300] if raw else '(空字符串)'}")

    d = parse(raw)
    if not d:
        print("[结果] 模型没给出可解析的 JSON —— 按硬规则3 当作安静，不出声。")
        return
    kind = str(d.get("kind", "quiet"))
    say = str(d.get("say", "")).strip()
    topic = str(d.get("topic", "")).strip()
    conf = float(d.get("confidence", 0))
    print(f"[判断] kind={kind} confidence={conf} topic={topic!r}")
    print(f"       say={say!r}")

    if kind not in ("companion", "offer") or not say or conf < 0.7:
        print("[结果] 不该开口（置信度不足或选择安静）——这本身就是正确行为。")
        return

    from sprite.proactive.help import publish, record, worth_saying
    if not worth_saying(topic, kind, say):
        print("[结果] 同一件事刚说过、他还没回应 -> 被时机闸拦下，不打扰。")
        return
    if not a.publish:
        print("[结果] 该开口。（加 --publish 才真发到气泡）")
        return
    offer = dict(id=f"{time.time_ns()}", t=time.time(), text=say, topic=topic, kind=kind,
                 action="none", confidence=conf)
    publish(offer)
    record(dict(offer, result="shown"))
    print(f"[结果] 已发布到 {HOME / 'perceive' / 'offer.json'}")


if __name__ == "__main__":
    main()