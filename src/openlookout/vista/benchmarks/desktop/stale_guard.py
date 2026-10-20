"""Stop repeating an action the live screen keeps invalidating.

A maintenance call that loses the race with the user (the scene changed
before trim/reclaim ran) used to be retried on the next heartbeat forever.
The second block inside a cooldown is terminal: drop the plan, do not retry
until that cooldown expires or the same action actually succeeds.
"""
from __future__ import annotations

import json

STALE_GIVE_UP = 2
STALE_COOLDOWN_S = 30 * 60

FIRST_BLOCK = "未执行：现场已有变化，请先读取新的 CURRENT 后重新判断。"
TERMINAL_BLOCK = (
    "未执行：同一动作已被现场变化拦住两次。放弃该动作，把 WORKING 里对应计划标成 dropped，"
    "本轮用 companion 收尾。这条事实重新出现之前不要重试。"
)


def action_key(name: str, arguments: dict | None) -> str:
    payload = {"tool": str(name or ""), "arguments": arguments or {}}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def note_stale_block(
    state: dict,
    key: str,
    *,
    now: float,
    cooldown_s: float = STALE_COOLDOWN_S,
) -> tuple[dict, str]:
    """Return a new ledger and the tool-result text. Does not mutate ``state``."""
    fresh = {
        item_key: item
        for item_key, item in state.items()
        if isinstance(item, dict) and now - float(item.get("at", 0) or 0) < cooldown_s
    }
    previous = int((fresh.get(key) or {}).get("count", 0) or 0)
    count = previous + 1
    fresh[key] = {"count": count, "at": now}
    text = TERMINAL_BLOCK if count >= STALE_GIVE_UP else FIRST_BLOCK
    return fresh, text


def note_stale_success(state: dict, key: str) -> dict:
    """Forget a key after the action really ran. Does not mutate ``state``."""
    if key not in state:
        return state
    return {item_key: item for item_key, item in state.items() if item_key != key}
