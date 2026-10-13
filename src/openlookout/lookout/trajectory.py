"""持续轨迹原型：把日常辅助与方向分支放进同一条反馈链。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from . import common, detectors, nexus, trends
from .v1 import build_tree
from .judgment import decide


ASSIST_ACTIONS = {
    "periodic_assembly": "在生成同类文件前自动核对输入与输出。",
    "manual_summary": "在提交汇总前自动与源表重算并标出差异。",
    "report_mismatch": "把本次差异变成下一次报告生成前的自动检查。",
    "numbered_series": "为系列任务保留可重跑的交付清单，避免重复整理。",
    "repeated_lookup": "把重复查询沉淀成可复用的查询和结果核对步骤。",
    "duplicate_charge": "新账单到来时自动比较历史扣费并标出重复项。",
    "price_change": "新账单到来时自动比较历史价格并标出变化。",
    "numeric_drift": "新数据进入时自动检查是否越过已有基线。",
    "tool_stack_churn": "把当前项目的约束和决定沉淀成跨代理上下文。",
}

DIRECTION_KINDS = {
    "tool_stack_churn",
    "openlookout_build",
    "numbered_series",
    "periodic_assembly",
    "report_mismatch",
    "numeric_drift",
}


def _normalize(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[\s\u3000]+", " ", text)
    text = re.sub(r"[，。！？、；：,.!?;:]+", " ", text)
    return text.strip()


def _item_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def load_corrections(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    rows = []
    for line in text.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_feedback(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def apply_feedback(items: list[dict], feedback: list[dict]) -> list[dict]:
    out = []
    for item in items:
        item = dict(item)
        item["judgment"] = decide(item, feedback)
        out.append(item)
    return out


def correction_assists(corrections: list[dict], min_repeat: int = 2) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in corrections:
        instruction = row.get("instruction") or row.get("text")
        if not instruction:
            continue
        scope = str(row.get("scope") or row.get("project") or "global")
        key = (_normalize(instruction), scope)
        groups.setdefault(key, []).append(row)
    out = []
    for (normalized, scope), rows in groups.items():
        if len(rows) < min_repeat:
            continue
        original = str(rows[-1].get("instruction") or rows[-1].get("text"))
        dates = sorted(str(row.get("ts") or row.get("date") or "")[:10] for row in rows)
        out.append({
            "id": _item_id("assist", f"{normalized}|{scope}"),
            "kind": "repeated_correction",
            "status": "candidate",
            "title": "把重复纠正变成默认行为",
            "rule": original,
            "scope": scope,
            "evidence": {"repetitions": len(rows), "dates": dates, "sources": [row.get("source") for row in rows if row.get("source")]},
            "action": "生成规则候选，确认后注入项目或用户级 Agent 上下文。",
        })
    return sorted(out, key=lambda item: (-item["evidence"]["repetitions"], item["id"]))


def finding_assists(findings: list[dict], min_score: float = 8) -> list[dict]:
    out = []
    for finding in findings:
        kind = finding.get("kind")
        action = ASSIST_ACTIONS.get(kind)
        if not action or float(finding.get("score") or 0) < min_score:
            continue
        facts = finding.get("facts") or {}
        out.append({
            "id": _item_id("assist", json.dumps({"kind": kind, "facts": facts}, ensure_ascii=False, sort_keys=True, default=str)),
            "kind": kind,
            "status": "candidate",
            "title": "把重复工作变成下一次的默认辅助",
            "action": action,
            "evidence": {"score": finding.get("score"), "facts": facts},
        })
    return out


def _next_test(kind: str) -> str:
    tests = {
        "tool_stack_churn": "在同一个小改动上使用项目上下文文件，比较是否减少代理切换和重复解释。",
        "numbered_series": "用最近一组输入重跑一次系列任务，比较文件数量和命名是否稳定。",
        "periodic_assembly": "在下一次生成前运行源表与输出核对，记录是否仍需手工修正。",
        "repeated_lookup": "把下一次查询记录成结构化结果，比较是否还要重新搜索同一问题。",
        "openlookout_build": "用一个真实项目任务跑一次新的上下文规则，比较是否减少重复解释。",
    }
    return tests.get(kind, "用下一次同类任务做一次前后对照，确认这个分支是否改变结果。")


def branch_candidates(findings: list[dict], catalog: dict | None = None, min_score: float = 8) -> list[dict]:
    grouped: dict[tuple[str, str], list[tuple[dict, dict]]] = {}
    for finding in findings:
        kind = finding.get("kind")
        if kind not in DIRECTION_KINDS or float(finding.get("score") or 0) < min_score:
            continue
        matches = trends.match_trends(finding, catalog=catalog, limit=1)
        if not matches:
            continue
        trend = matches[0]
        grouped.setdefault((kind, trend["id"]), []).append((finding, trend))
    out = []
    for (kind, trend_id), observations in grouped.items():
        finding, trend = max(observations, key=lambda pair: float(pair[0].get("score") or 0))
        out.append({
            "id": _item_id("branch", f"{kind}|{trend_id}"),
            "status": "new",
            "title": f"重新看待“{kind}”：{trend.get('opens') or trend.get('fact')}",
            "trigger": f"{len(observations)} 个同类行为观察与一条外部能力变化发生交汇。",
            "why_now": trend.get("fact", "") ,
            "evidence": {
                "behavior_kind": kind,
                "behavior_score": finding.get("score"),
                "behavior_facts": finding.get("facts") or {},
                "observations": len(observations),
                "external": trends.cite(trend),
            },
            "next_test": _next_test(kind),
        })
    return out


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"seen_assists": [], "seen_branches": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _mark_new(items: list[dict], seen: set[str]) -> list[dict]:
    for item in items:
        item["new"] = item["id"] not in seen
    return items


def render_markdown(summary: dict) -> str:
    lines = ["# OpenLookout Trajectory\n", f"生成时间：{summary['generated_at']}\n"]
    lines.append("\n## 日常辅助候选\n")
    assists = summary["assist_candidates"]
    if not assists:
        lines.append("暂无达到重复阈值的辅助候选。\n")
    for item in assists:
        marker = "新" if item.get("new") else "已见"
        lines.append(f"- **[{marker}] {item['title']}**：{item.get('action', '')}\n")
        if item.get("rule"):
            lines.append(f"  - 规则：{item['rule']}（范围：{item['scope']}）\n")
        lines.append(f"  - 证据：{json.dumps(item['evidence'], ensure_ascii=False)}\n")
    lines.append("\n## 值得尝试的岔路\n")
    branches = summary["branch_candidates"]
    if not branches:
        lines.append("暂无同时具备行为证据和外部变化的岔路。\n")
    for item in branches:
        marker = "新" if item.get("new") else "已见"
        ext = item["evidence"]["external"]
        lines.extend([
            f"- **[{marker}] {item['title']}**\n",
            f"  - 为什么现在：{item['why_now']}\n",
            f"  - 行为证据：{json.dumps(item['evidence']['behavior_facts'], ensure_ascii=False)}\n",
            f"  - 外部来源：{ext['url']}（{ext['date']}）\n",
            f"  - 最小验证：{item['next_test']}\n",
        ])
    review = summary.get("model_review")
    if review:
        lines.append("\n## 模型证据审查\n")
        if review.get("error"):
            lines.append(f"- 审查失败：{review['error']}\n")
        else:
            result = review.get("review") or {}
            lines.append(f"- 模型：`{review.get('model')}`\n")
            lines.append(f"- 是否保留岔路：{result.get('keep_branch')}\n")
            lines.append(f"- 理由：{result.get('reason', '')}\n")
            lines.append(f"- 更好的验证：{result.get('better_test', '')}\n")
    return "".join(lines)


def _review_payload(summary: dict) -> dict:
    return {
        "assist_candidates": [
            {"kind": item.get("kind"), "evidence": item.get("evidence"), "action": item.get("action")}
            for item in summary["assist_candidates"]
        ],
        "branch_candidates": [
            {
                "kind": item["evidence"]["behavior_kind"],
                "behavior_score": item["evidence"]["behavior_score"],
                "behavior_facts": item["evidence"]["behavior_facts"],
                "external": item["evidence"]["external"],
                "next_test": item["next_test"],
            }
            for item in summary["branch_candidates"]
        ],
    }


def review_with_model(summary: dict, out: Path, model: str) -> dict:
    from .llm import LLM, parse_json

    system = (
        "你是 OpenLookout 的证据审查员。判断候选是否真的值得打扰用户。"
        "只根据结构化事实，不补造用户意图。"
        "只输出 JSON：{\"keep_branch\":true/false,\"reason\":\"一句话\",\"better_test\":\"一个最小验证\"}。"
    )
    try:
        llm = LLM(out, model)
        text, usage = llm.chat("trajectory_evidence_review", system, json.dumps(_review_payload(summary), ensure_ascii=False), max_tokens=800, temperature=0)
        return {"model": model, "review": parse_json(text), "usage": usage}
    except Exception as error:
        return {"model": model, "error": repr(error)[:300]}


def run(capture: Path, out: Path, corrections_path: Path | None = None, min_repeat: int = 2, review_model: str | None = None, feedback_path: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    common.CAP = capture.resolve()
    tree, content_count = build_tree(common.CAP)
    common.SIM = tree
    evs, meta = common.load_events(), common.load_meta()
    meta["user_home"] = str(tree)
    meta["watched_dirs"] = [item.name for item in tree.iterdir() if item.is_dir()]
    findings = detectors.run_all(evs, meta)
    findings += nexus.detect_tool_stack_churn(evs, meta)
    findings += nexus.detect_openlookout_build(evs, meta)
    findings.sort(key=lambda item: -float(item.get("score") or 0))
    for index, finding in enumerate(findings, 1):
        finding.setdefault("id", f"T{index}")
    catalog = trends.load_catalog()
    state_path = out / "trajectory_state.json"
    state = _load_state(state_path)
    assists = finding_assists(findings) + correction_assists(load_corrections(corrections_path), min_repeat=min_repeat)
    branches = branch_candidates(findings, catalog=catalog)
    feedback = load_feedback(feedback_path)
    assists = apply_feedback(assists, feedback)
    branches = apply_feedback(branches, feedback)
    _mark_new(assists, set(state.get("seen_assists", [])))
    _mark_new(branches, set(state.get("seen_branches", [])))
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "capture": str(capture.resolve()),
        "stats": {"events": len(evs), "findings": len(findings), "content_files": content_count},
        "feedback_count": len(feedback),
        "assist_candidates": assists,
        "branch_candidates": branches,
        "findings": [{"id": f.get("id"), "kind": f.get("kind"), "score": f.get("score"), "facts": f.get("facts") or {}} for f in findings],
    }
    if review_model:
        summary["model_review"] = review_with_model(summary, out, review_model)
        (out / "model_review.json").write_text(json.dumps(summary["model_review"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "trajectory.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "trajectory.md").write_text(render_markdown(summary), encoding="utf-8")
    state["seen_assists"] = sorted(set(state.get("seen_assists", [])) | {item["id"] for item in assists})
    state["seen_branches"] = sorted(set(state.get("seen_branches", [])) | {item["id"] for item in branches})
    (out / "trajectory_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="OpenLookout 持续辅助 + 岔路原型")
    parser.add_argument("--capture", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--corrections")
    parser.add_argument("--min-repeat", type=int, default=2)
    parser.add_argument("--review-model", help="可选：用 OpenAI 兼容模型审查候选证据，例如 mimo-v2.6-flash")
    parser.add_argument("--feedback")
    args = parser.parse_args(argv)
    summary = run(Path(args.capture), Path(args.out), Path(args.corrections) if args.corrections else None, args.min_repeat, args.review_model, Path(args.feedback) if args.feedback else None)
    print(f"trajectory done: events={summary['stats']['events']} findings={summary['stats']['findings']} "
          f"assists={len(summary['assist_candidates'])} branches={len(summary['branch_candidates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
