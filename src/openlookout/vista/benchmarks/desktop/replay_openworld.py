"""Blind proactive discovery replay with real model calls and isolated files."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import uuid
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from sprite.proactive import conversation, help as helpmod
from sprite.proactive.provider import load_provider
from vista.core.contracts import ToolBinding, ToolReply, Visual
from vista.core.profiles import Phase
from vista.core.runtime import TaskRuntime
from . import actions, brain, historyfacts, session as sessionmod
from .agenda import Agenda
from .decision_engine import DecisionEngine
from .profiles import VISTA_TOOLS, make_experiment, make_profile


def verified_table(files: list[dict], scenario: str) -> bool:
    scenario = "purchase" if scenario == "blind-purchase" else scenario
    expected = ({"支架": {450, 375, 75}, "导线": {128}, "接头": {63}, "总计": {641, 566, 75}}
                if scenario == "purchase" else {"A": {24, 24000}, "B": {24}})
    found = set()
    for item in files:
        for line in item["content"].splitlines():
            cells = ([cell.strip().strip("*") for cell in line.strip().strip("|").split("|")]
                     if line.strip().startswith("|") else next(csv.reader([line]), []))
            if not cells:
                continue
            label = cells[0].strip()
            if scenario == "purchase" and label in {"合计", "三行合计", "总金额"}:
                label = "总计"
            values = {abs(float(match)) for cell in cells[1:]
                      for match in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", cell)}
            if label in expected and expected[label].issubset(values):
                found.add(label)
    return found == set(expected)


def prepare_blind_fixture(workspace: Path, *, clean: bool) -> list[dict]:
    workspace.mkdir(parents=True)
    (workspace / "workflow.txt").write_text(
        "器材采购交付格式：release.csv 使用 CNY 含税金额，保留每项总金额与合计。"
        "reference.csv 来自供应方，含数量及含税单价。archive.csv 是上期交付记录。\n", encoding="utf-8")
    (workspace / "reference.csv").write_text(
        "item,quantity,unit_price,currency\n支架,12,37.5,CNY\n导线,8,16,CNY\n接头,15,4.2,CNY\n", encoding="utf-8")
    correct = "item,total,currency\n支架,450,CNY\n导线,128,CNY\n接头,63,CNY\n总计,641,CNY\n"
    (workspace / "release.csv").write_text(correct if clean else
        "item,total,currency\n支架,375,CNY\n导线,128,CNY\n接头,63,CNY\n总计,566,CNY\n", encoding="utf-8")
    (workspace / "archive.csv").write_text(
        "item,quantity,unit_price,total,currency\n支架,10,37.5,375,CNY\n导线,8,16,128,CNY\n接头,15,4.2,63,CNY\n总计,,,566,CNY\n", encoding="utf-8")
    (workspace / "reading.txt").write_text("城市公园：树荫与步道帮助居民享受户外时间。\n", encoding="utf-8")
    operations = [("activity", "resource_sample", None), ("recent", "file_open", "reading.txt"),
                  ("recent", "file_open", "archive.csv"), ("recent", "file_open", "workflow.txt"),
                  ("recent", "file_open", "reference.csv"), ("recent", "file_save", "release.csv"),
                  ("activity", "file_open", "reference.csv"), ("activity", "file_open", "release.csv"),
                  ("activity", "file_open", "reference.csv"), ("activity", "file_save", "release.csv"),
                  ("activity", "file_open", "reading.txt"), ("activity", "resource_sample", None)]
    records = []
    for index, (source, event, filename) in enumerate(operations):
        record = {"source": source, "type": event, "ts": f"2026-10-12T12:{index:02d}:00+00:00"}
        if filename:
            record["path"] = str(workspace / filename)
        else:
            record.update(memory_percent=94, ui_response_ms=25, save_failures=0)
        records.append(record)
    return records


def isolated_reader(roots: list[Path], receipts: list[dict]):
    resolved_roots = [root.resolve() for root in roots]

    def read(arguments):
        raw_path = Path(str(arguments.get("path", "")))
        path = raw_path.resolve()
        allowed = raw_path.is_absolute() and any(path.is_relative_to(root) for root in resolved_roots)
        receipt = {"path": str(path) if allowed else "outside-isolated-workspace", "allowed": allowed,
                   "offset": arguments.get("offset", 0), "limit": arguments.get("limit", 5000)}
        receipts.append(receipt)
        if not allowed:
            return ToolReply("回放只允许读取合成 workspace 和本次 deliverables；未读取外部文件。", success=False)
        reply = historyfacts.read_local(arguments)
        receipt.update(success=reply.success, returned_bytes=len(reply.text.encode("utf-8")))
        return reply

    return read


def clean_success(files: list[dict], turns: list[dict], goals: list[dict], receipts: list[dict]) -> bool:
    """Return true only when the clean contrast actually ran and stayed quiet."""
    return (bool(turns) and all(row.get("boundary") == "decision_complete" and not row.get("returncode")
                                and not row.get("say") for row in turns)
            and bool(receipts) and all(row.get("allowed") and row.get("success") for row in receipts))


def replay_history(records: list[dict], *, paged: bool = False):
    rows = [dict(row, category=row.get("category", row.get("source"))) for row in records]
    if paged:
        rows = [{"category": "browser", "source": "browser", "type": "visit", "url": "https://example.org/reading",
                 "title": "reading", "ts": "2026-10-12T12:01:00+00:00"},
                {"category": "activity", "source": "recorder:activity", "type": "focus", "title": "editor",
                 "ts": "2026-10-12T12:00:00+00:00"}] + rows
    snapshot_id = "replay-" + historyfacts.uuid.uuid4().hex
    historyfacts.SNAPSHOTS[snapshot_id] = {
        "captured_at": time.time(), "days": 14, "sources": sorted(historyfacts.SOURCES), "records": rows,
        "coverage": [{"source": source, "ok": True} for source in sorted(historyfacts.SOURCES)],
        "limitations": ["操作记录不证明困难、未来安排或完成，需要读取实际资料判断。"]}

    def read(arguments):
        options = dict(arguments)
        if options.get("snapshot") and options["snapshot"] != snapshot_id:
            return ToolReply("回放只允许查询本次合成快照。", success=False)
        if not options.get("offset") or options.get("snapshot"):
            options["snapshot"] = options.get("snapshot") or snapshot_id
        if paged:
            options["limit"] = min(options.get("limit", 2), 2)
        return historyfacts.query(options)

    return read


def run(*, clean: bool = False, turns: int = 3, scenario: str = "purchase", paged: bool = False) -> dict:
    provider = load_provider()
    directory = brain.HOME / "openworld_replay" / (time.strftime("%Y%m%d-%H%M%S") + "-" + scenario
                                                + ("-paged" if paged else "") + ("-clean" if clean else "-problem"))
    if scenario == "blind-purchase":
        directory = brain.HOME / "openworld_replay" / (time.strftime("%Y%m%d-%H%M%S") + "-synthetic-" + uuid.uuid4().hex[:8])
    workspace = directory / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "delivery-notes.txt").write_text(
        "月度器材采购核对\n成本采用数量乘单价。报价单币种是 CNY，单价已含税。"
        "export.csv 是当前交付物，只需三行明细与总计。若金额有差异，准备指出差异的核对表；"
        "现有交付物已经正确则不用另做。不需要更改采购系统。\n", encoding="utf-8")
    (workspace / "quote.csv").write_text(
        "item,quantity,unit_price,currency\n支架,12,37.5,CNY\n导线,8,16,CNY\n接头,15,4.2,CNY\n", encoding="utf-8")
    (workspace / "export.csv").write_text(
        "item,total,currency\n支架,450,CNY\n导线,128,CNY\n接头,63,CNY\n总计,641,CNY\n" if clean else
        "item,total,currency\n支架,375,CNY\n导线,128,CNY\n接头,63,CNY\n总计,566,CNY\n", encoding="utf-8")
    records = [
        {"source": "recent", "event": "file_open", "path": str(workspace / "delivery-notes.txt")},
        {"source": "recent", "event": "file_open", "path": str(workspace / "quote.csv")},
        {"source": "recent", "event": "file_save", "path": str(workspace / "export.csv")},
        {"source": "activity", "event": "file_open", "path": str(workspace / "quote.csv")},
        {"source": "activity", "event": "file_open", "path": str(workspace / "export.csv")},
        {"source": "activity", "event": "file_save", "path": str(workspace / "export.csv")},
    ]
    if scenario == "measurement":
        (workspace / "delivery-notes.txt").write_text(
            "样品测量记录：报告体积统一使用 cm^3。长宽高以原始记录为准；矩形体体积=长×宽×高。"
            "发现差异时准备逐行核对表，注明换算和差异，不改原始测量值。\n", encoding="utf-8")
        (workspace / "quote.csv").write_text(
            "sample,length,width,height,unit\nA,20,30,40,mm\nB,2,3,4,cm\n", encoding="utf-8")
        (workspace / "export.csv").write_text(
            "sample,volume,unit\nA,24,cm^3\nB,24,cm^3\n" if clean else
            "sample,volume,unit\nA,24000,cm^3\nB,24,cm^3\n", encoding="utf-8")
    if scenario == "blind-purchase":
        records = prepare_blind_fixture(workspace / "operations", clean=clean)
        workspace = workspace / "operations"
    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), "white").save(buffer, "JPEG")
    visual = Visual("screen", "replay-blank", buffer.getvalue(), 320, 200, mime_type="image/jpeg")
    deliverables = directory / "deliverables"
    history_args = []
    source_receipts = []
    history_reader = replay_history(records, paged=paged)

    def read_history(arguments):
        history_args.append(arguments)
        return history_reader(arguments)

    results = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(actions, "DELIVERABLES", deliverables))
        stack.enter_context(patch.object(actions, "JOURNAL", directory / "undo.jsonl"))
        stack.enter_context(patch.object(sessionmod, "CURRENT", directory / "current.json"))
        stack.enter_context(patch.object(conversation, "history", lambda limit=80: []))
        stack.enter_context(patch.object(helpmod, "DIR", directory))
        stack.enter_context(patch.object(helpmod, "OFFER", directory / "offer.json"))
        stack.enter_context(patch.object(helpmod, "OFFER_LOG", directory / "offers.jsonl"))
        stack.enter_context(patch.object(brain, "residual_fact", lambda **kwargs: ""))
        stack.enter_context(patch.object(brain, "long_term_fact", lambda **kwargs: ""))
        stack.enter_context(patch.object(brain, "PERCEIVE", directory))
        allowed = VISTA_TOOLS + ("desktop_history", "desktop_read_local", "basic_calculate",
                                  "desktop_plan", "desktop_write_deliverable", "companion")
        profile = replace(make_profile(), tools=allowed)
        session = sessionmod.DesktopSession("结合持续画面与真实操作痕迹，自主发现值得帮助的事情、准备下一步；看准时机交流或报告有用的结果。", {}, visual=visual)
        handlers = {"desktop_history": read_history,
                    "desktop_read_local": isolated_reader([workspace, deliverables], source_receipts)}
        session.tools = tuple(ToolBinding(binding.spec, session._handler(binding.spec.name, handlers[binding.spec.name]))
                              if binding.spec.name in handlers else binding for binding in session.tools)
        session.agenda = Agenda(DecisionEngine(), directory / "agenda.json")
        experiment = make_experiment(profile, backend="claude", model=provider.model, effort="low",
                                     revision="blind-openworld-replay", presentation={})
        runtime = TaskRuntime(session, experiment, artifact_dir=directory / "artifacts")
        for note in (runtime.context.guide_path, runtime.context.working_path):
            if note:
                Path(note).write_text("", encoding="utf-8")
        backend = brain.VisualDirectBackend({"model": provider.model, "base_url": provider.base_url,
                                            "api_key": provider.api_key}, runtime)
        backend.attach(session)
        continuations = brain.ContinuationTracker()
        try:
            for turn in range(turns):
                before = len(session.decisions)
                started = time.perf_counter()
                text = ("用户没有给你派新任务；空白图无额外信息。真实操作记录可用 desktop_history 查询。"
                        f"本机可创建交付物的目录：{deliverables}。只依据证据判断是否有帮助机会，"
                        "资料齐全且无问题时也可能安静，不必为了忙碌制造工作。")
                evidence_revision = session.evidence_revision
                key = continuations.pending(session.decisions[-1] if session.decisions else {}, evidence_revision, session.agenda)
                if key:
                    continuations.consume(key, evidence_revision)
                    text += "\n【续办】这是你选择的可执行下一步：" + json.dumps(continuations.step, ensure_ascii=False)
                text += "\n" + session.agenda.context()
                reply = backend.run(runtime.prepare_input(Phase.INITIAL if turn == 0 else Phase.STEP, public_text=text))
                decision = session.decisions[-1] if len(session.decisions) > before else {}
                row = {"turn": turn + 1, "boundary": reply.boundary, "say": decision.get("say"),
                       "next_step": decision.get("next_step"), "returncode": reply.returncode,
                       "elapsed_s": round(time.perf_counter() - started, 1)}
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                if reply.returncode:
                    break
                if deliverables.exists() and any(deliverables.iterdir()) and all(
                        goal.state in {"done", "dropped", "waiting"} for goal in session.agenda.goals.values()):
                    break
                if continuations.pending(decision, session.evidence_revision, session.agenda) is None and not session.agenda.due():
                    break
        finally:
            runtime.close()
    files = [{"path": str(path), "content": path.read_text(encoding="utf-8")}
             for path in deliverables.glob("*") if path.is_file()]
    events = [json.loads(line) for line in (directory / "artifacts" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    reads = {event["call_id"]: event.get("arguments", {}).get("path", "") for event in events
             if event.get("event") == "tool_started" and event.get("tool") == "desktop_read_local"}
    independently_read = False
    for event in events:
        if event.get("event") != "tool_result" or not event.get("success") or event.get("call_id") not in reads:
            continue
        try:
            result = json.loads(event["text"].split("\n目标结果 result_id=", 1)[0])
        except (ValueError, TypeError):
            continue
        if any(reads[event["call_id"]] == item["path"] and result.get("text") == item["content"] for item in files):
            independently_read = True
    table_content_verified = verified_table(files, scenario)
    goals_done = bool(session.agenda.goals) and all(goal.state == "done" for goal in session.agenda.goals.values())
    permission_questions = any(any(phrase in str(row.get("say") or "") for phrase in ("要我", "需要我", "可以吗", "要不要")) for row in results)
    usage = [event for event in events if event.get("event") == "model_usage"]
    outcome = {"directory": str(directory), "clean": clean, "scenario": scenario, "paged": paged, "history_queries": len(history_args),
               "history_arguments": history_args,
               "source_receipts": source_receipts,
               "privacy_scope": {"data": "synthetic operations and files; blank image; fresh VISTA notes",
                                 "read_roots": [str(workspace), str(deliverables)],
                                 "write_roots": [str(directory)], "outbound": "configured model only"},
               "model_usage": {"requests": len(usage),
                               "input_tokens": sum(event.get("input_tokens") or 0 for event in usage),
                               "output_tokens": sum(event.get("output_tokens") or 0 for event in usage),
                               "request_bytes": sum(event.get("request_bytes") or 0 for event in usage),
                               "monetary_cost": None, "cost_note": "provider pricing not available; token counts are receipts"},
               "turns": results, "files": files, "goals": {key: item.state for key, item in session.agenda.goals.items()},
               "independently_read": independently_read,
               "table_content_verified": table_content_verified,
               "permission_questions": permission_questions,
               "passed": bool(files) and table_content_verified and independently_read and goals_done and not permission_questions
               if not clean else clean_success(files, results, session.agenda.goals, source_receipts) and not files}
    (directory / "results.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in outcome.items() if key != "files"}, ensure_ascii=False), flush=True)
    return outcome


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--paged", action="store_true")
    parser.add_argument("--scenario", choices=["purchase", "measurement", "blind-purchase"], default="purchase")
    options = parser.parse_args()
    run(clean=options.clean, turns=options.turns, scenario=options.scenario, paged=options.paged)
