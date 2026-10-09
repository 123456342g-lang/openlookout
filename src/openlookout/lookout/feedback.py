"""用户反馈：把「不重要」写回排序。

默认种子：用户已口头确认考勤汇总不重要 → 大幅降权 manual_summary（路径含考勤）。
反馈文件可追加，不进私有数据仓库时用仓库内默认规则。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "lookout" / "feedback_rules.json"

DEFAULT_RULES = {
    "version": 1,
    "rules": [
        {
            "id": "attendance_unimportant",
            "action": "demote",
            "factor": 0.05,
            "match": {
                "kind": "manual_summary",
                "any_path_regex": [r"考勤", r"出勤", r"attendance"],
            },
            "reason": "用户明确表示考勤表不重要（2026-10-09）",
        },
        {
            "id": "prefer_crypto_series",
            "action": "boost",
            "factor": 1.35,
            "match": {
                "kind": "numbered_series",
                "any_path_regex": [r"密码", r"crypto", r"Cryptography"],
            },
            "reason": "用户明确表示应用密码学实验重要",
        },
        {
            "id": "prefer_tool_churn",
            "action": "boost",
            "factor": 1.25,
            "match": {"kind": "tool_stack_churn"},
            "reason": "用户在 AI 编程工具上反复折腾，优先连外部新能力",
        },
        {
            "id": "prefer_openlookout",
            "action": "boost",
            "factor": 1.2,
            "match": {"kind": "openlookout_build"},
            "reason": "用户正在做 OpenLookout 本身",
        },
    ],
}


def load_rules(path: Path | None = None) -> dict:
    p = path or DEFAULT_PATH
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return DEFAULT_RULES


def ensure_default_file(path: Path | None = None) -> Path:
    p = path or DEFAULT_PATH
    if not p.exists():
        p.write_text(json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _blob(f: dict) -> str:
    return json.dumps({"local": f.get("local"), "facts": f.get("facts"), "desc": f.get("desc")}, ensure_ascii=False)


def _match(rule: dict, f: dict) -> bool:
    m = rule.get("match") or {}
    if m.get("kind") and f.get("kind") != m["kind"]:
        return False
    blob = _blob(f)
    for rx in m.get("any_path_regex") or []:
        if re.search(rx, blob, re.I):
            return True
    if not m.get("any_path_regex"):
        return True
    return False


def multiplier(f: dict, rules: dict | None = None) -> tuple[float, list[dict]]:
    """返回 (乘数, 命中规则列表)。demote 用小因子，boost 用 >1。"""
    rules = rules or load_rules()
    mult = 1.0
    hits = []
    for r in rules.get("rules") or []:
        if not _match(r, f):
            continue
        hits.append({"id": r["id"], "action": r["action"], "factor": r["factor"], "reason": r.get("reason")})
        if r["action"] == "demote":
            mult *= float(r["factor"])
        elif r["action"] == "boost":
            mult *= float(r["factor"])
    return mult, hits
