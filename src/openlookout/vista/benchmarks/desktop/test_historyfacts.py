from __future__ import annotations

import json
from types import SimpleNamespace

from vista.benchmarks.desktop import actions, brain, historyfacts
from vista.benchmarks.desktop.profiles import TOOLS
from vista.benchmarks.desktop.session import DesktopSession


def payload(reply):
    return json.loads(reply.text)


def test_history_pages_one_snapshot_without_rereading(monkeypatch):
    calls = []

    def collect(days, sources):
        calls.append((days, sources))
        return {"captured_at": 1, "days": days, "sources": sorted(sources),
                "coverage": [{"source": "recent", "ok": True}], "limitations": ["not a deadline"],
                "records": [{"path": f"C:/work/item-{index}.txt", "ts": str(index)} for index in range(5)]}

    monkeypatch.setattr(historyfacts, "collect", collect)
    first = payload(historyfacts.query({"sources": ["recent"], "limit": 2}))
    second = payload(historyfacts.query({"snapshot": first["snapshot"], "offset": first["next_offset"], "limit": 2}))
    narrowed = payload(historyfacts.query({"snapshot": first["snapshot"], "query": "item-4"}))
    assert len(calls) == 1
    assert second["records"][0]["path"] == "C:/work/item-2.txt"
    assert narrowed["total_matches"] == 1
    assert narrowed["next_offset"] is None
    assert narrowed["limitations"] == ["not a deadline"]


def test_history_refuses_unstable_paging_and_unknown_snapshot():
    assert not historyfacts.query({"offset": 2}).success
    assert not historyfacts.query({"snapshot": "expired"}).success
    assert not historyfacts.query({"sources": ["cookies"]}).success


def test_feed_delivers_real_source_samples_without_model_search(monkeypatch):
    calls = []
    rows = [{"category": "browser", "url": f"https://example.org/page-{index}", "ts": "2026-10-11T12:00:00+00:00"}
            for index in range(5)] + [
        {"category": "recent", "path": "C:/work/input.docx", "ts": "2026-10-10T12:00:00+00:00"},
        {"category": "activity", "type": "focus", "title": "actual work", "dur_s": 120, "ts": "2026-10-11T12:01:00+00:00"}]

    def collect(days, sources):
        calls.append(days)
        return {"captured_at": 1, "days": days, "sources": sorted(sources), "records": rows,
                "coverage": [{"source": "office", "ok": False}], "limitations": ["not proof of completion"]}

    monkeypatch.setattr(historyfacts, "collect", collect)
    feed = historyfacts.HistoryFeed(SimpleNamespace(observe=lambda now: "sources changed"))
    first = feed.observe(100)
    data = json.loads(first.splitlines()[1])
    samples = {sample["source"]: sample for sample in data["samples"]}
    assert len(calls) == 1
    assert samples["recent"]["records"][0]["path"] == "C:/work/input.docx"
    assert samples["activity"]["records"][0]["dur_s"] == 120
    assert samples["browser"]["next_offset"] == 2
    assert data["coverage"][0]["ok"] is False
    page = payload(historyfacts.query({"snapshot": data["snapshot"], "sources": ["browser"], "offset": 2}))
    assert len(page["records"]) == 3
    assert feed.observe(131) == ""
    assert json.loads(feed.context.splitlines()[1])["snapshot"] in historyfacts.SNAPSHOTS


def test_recorded_activity_preserves_sequence_without_clipboard_content(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    stamp = datetime.now(timezone.utc) - timedelta(hours=1)
    path = tmp_path / "operations.jsonl"
    events = [{"type": "focus", "ts": stamp.isoformat(), "app": "reader", "title": "requirements", "dur_s": 100},
              {"type": "clipboard", "ts": (stamp + timedelta(minutes=1)).isoformat(), "len": 24,
               "text": "PRIVATE_CLIPBOARD", "hash": "private hash"},
              {"type": "file_save", "ts": (stamp + timedelta(minutes=2)).isoformat(), "path": "C:/work/result.docx"}]
    path.write_text("\n".join(json.dumps(row) for row in events) + "\nunfinished", encoding="utf-8")
    monkeypatch.setattr(historyfacts, "operation_paths", lambda: [path])
    result = historyfacts.collect(14, {"activity"})
    assert len(result["records"]) == 3
    assert "PRIVATE_CLIPBOARD" not in json.dumps(result)
    assert all("hash" not in row and "text" not in row for row in result["records"])
    monkeypatch.setitem(historyfacts.SNAPSHOTS, "activity-sequence", result)
    sequence = payload(historyfacts.query({"snapshot": "activity-sequence", "view": "events", "order": "asc",
                                          "since": stamp.isoformat(), "until": (stamp + timedelta(minutes=2)).isoformat()}))
    assert [row["type"] for row in sequence["records"]] == ["focus", "clipboard", "file_save"]
    assert not historyfacts.query({"snapshot": "activity-sequence", "since": "not a time"}).success
    assert not historyfacts.query({"snapshot": "activity-sequence", "sources": ["office"]}).success


def test_long_activity_log_pages_without_losing_boundary_events_or_chasing_appends(tmp_path):
    path = tmp_path / "operations.jsonl"
    rows = [{"seq": index, "ts": "2026-10-11T12:00:00+00:00", "title": "x" * 1100} for index in range(2000)]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    latest, before = historyfacts.activity_events(path)
    assert before is not None
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"seq": 2000, "ts": "2026-10-11T12:01:00+00:00"}) + "\n")
    earlier, exhausted = historyfacts.activity_events(path, before)
    assert exhausted is None
    assert [row["seq"] for row in earlier + latest] == list(range(2000))


def test_collect_reuses_readers_preserves_actual_paths_and_partial_failure(monkeypatch):
    def recent(appdata, context):
        context["emit"]({"ts": "2026-10-01T08:00:00+08:00", "path": context["mapper"]("C:/school/task.docx"),
                         "type": "file_open", "source": "backfill:recent"})

    def office(context):
        raise OSError("unavailable")

    monkeypatch.setattr(historyfacts.backfill, "read_recent", recent)
    monkeypatch.setattr(historyfacts.backfill, "read_office_mru", office)
    result = historyfacts.collect(14, {"recent", "office"})
    assert result["records"][0]["path"] == "C:/school/task.docx"
    assert result["records"][0]["category"] == "recent"
    assert result["coverage"][-1] == {"source": "office", "ok": False, "error": "OSError"}


def test_local_document_paging_and_legacy_encoding(tmp_path):
    document = tmp_path / "requirements.txt"
    document.write_bytes("实验要求：保留单位和参数".encode("gb18030"))
    first = payload(historyfacts.read_local({"path": str(document), "limit": 5}))
    second = payload(historyfacts.read_local({"path": str(document), "offset": first["next_offset"]}))
    assert first["text"] + second["text"] == "实验要求：保留单位和参数"
    assert second["next_offset"] is None


def test_docx_preserves_requirements_in_table_cells(tmp_path):
    import zipfile

    document = tmp_path / "requirements.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>截图必须有单位</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    assert payload(historyfacts.read_local({"path": str(document)}))["text"] == "截图必须有单位"


def test_local_read_refuses_credentials_and_unsupported_documents(tmp_path):
    for name in (".env", "Cookies", "requirements.doc"):
        document = tmp_path / name
        document.write_text("secret-or-binary", encoding="utf-8")
        assert not historyfacts.read_local({"path": str(document)}).success


def test_history_queries_do_not_count_as_actions(monkeypatch):
    session = object.__new__(DesktopSession)
    session.actions = actions.MAX_ACTIONS
    session.action_results = []
    session._turn_mutations = []
    for name in ("desktop_history", "desktop_read_local"):
        assert name in TOOLS
        assert session._handler(name, lambda args: historyfacts._reply({"ok": True}))({}).success
    assert session.actions == actions.MAX_ACTIONS
    assert not session.action_results


def test_working_survives_process_restart(tmp_path, monkeypatch):
    saved_guide = tmp_path / "saved-guide.md"
    saved_working = tmp_path / "saved-working.md"
    working = tmp_path / "WORKING.md"
    guide = tmp_path / "GUIDE.md"
    guide.write_text("preferences", encoding="utf-8")
    working.write_text("candidate, source, uncertainty, next query", encoding="utf-8")
    monkeypatch.setattr(brain, "GUIDE", saved_guide)
    monkeypatch.setattr(brain, "WORKING", saved_working)
    runtime = SimpleNamespace(context=SimpleNamespace(guide_path=guide, working_path=working))
    brain.save_guide(runtime)
    working.write_text("initial", encoding="utf-8")
    brain.restore_guide(runtime)
    assert working.read_text(encoding="utf-8") == "candidate, source, uncertainty, next query"


def test_model_retries_only_interrupted_transport(monkeypatch):
    import io
    import ssl
    import urllib.error

    requests = []

    def respond(request, timeout):
        requests.append(request)
        if len(requests) == 1:
            raise urllib.error.URLError(ssl.SSLEOFError("interrupted"))
        return io.BytesIO(b'{"content": []}')

    monkeypatch.setattr("urllib.request.urlopen", respond)
    request = object()
    assert brain.model_response(request) == {"content": []}
    assert requests == [request, request]


def test_model_does_not_retry_auth_or_certificate_errors(monkeypatch):
    import pytest
    import ssl
    import urllib.error

    for error in (urllib.error.HTTPError("https://configured.example", 401, "auth", {}, None),
                  urllib.error.URLError(ssl.SSLCertVerificationError("untrusted"))):
        calls = []

        def fail(request, timeout):
            calls.append(request)
            raise error

        monkeypatch.setattr("urllib.request.urlopen", fail)
        with pytest.raises(urllib.error.URLError):
            brain.model_response(object())
        assert len(calls) == 1


def test_history_source_updates_without_reading_contents(tmp_path, monkeypatch):
    import os

    source = tmp_path / "History"
    source.write_bytes(b"not even a database; metadata only")
    watcher = historyfacts.HistoryWatcher()
    watcher.paths = [("browser", source)]
    monkeypatch.setattr(historyfacts, "collect", lambda *args: (_ for _ in ()).throw(AssertionError("must not read")))
    assert "尚未读取内容" in watcher.observe(100)
    assert watcher.observe(131) == ""
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert "browser" in watcher.observe(162)
    assert "not even a database" not in watcher.observe(193)


def test_continuation_resumes_after_new_evidence_without_screen_change():
    tracker = brain.ContinuationTracker()
    decision = {"next_step": {"status": "ready", "goal": "核对缺口", "action": "读取下一段资料", "evidence": "线索"}}
    key = tracker.pending(decision, 0)
    assert key
    tracker.consume(key, 0)
    assert tracker.pending(decision, 0) is None
    decision["next_step"]["evidence"] = "只是换了种表述"
    assert tracker.pending(decision, 0) is None
    assert tracker.pending(decision, 1) == key
    decision["next_step"]["status"] = "waiting"
    assert tracker.pending(decision, 2) is None


def test_repeat_history_with_new_snapshot_is_not_new_evidence():
    session = object.__new__(DesktopSession)
    session._record_evidence("desktop_history", historyfacts._reply({"records": [{"path": "C:/notes.txt"}], "snapshot": "first", "captured_at": 1}))
    revision = session.evidence_revision
    session._record_evidence("desktop_history", historyfacts._reply({"records": [{"path": "C:/notes.txt"}], "snapshot": "second", "captured_at": 2}))
    assert session.evidence_revision == revision
    session._record_evidence("desktop_history", historyfacts._reply({"records": [{"path": "C:/results.txt"}], "snapshot": "second", "captured_at": 2}))
    assert session.evidence_revision == revision + 1


def test_search_rewording_does_not_create_evidence_without_changed_results():
    session = object.__new__(DesktopSession)
    result = {"ok": True, "root": "C:/one-project", "matches": [], "truncated": True,
              "query": "first hypothesis", "scanned": 2500}
    session._record_evidence("basic_search", historyfacts._reply(result))
    revision = session.evidence_revision
    session._record_evidence("basic_search", historyfacts._reply(dict(result, query="second hypothesis")))
    assert session.evidence_revision == revision
    session._record_evidence("basic_search", historyfacts._reply(dict(result, matches=[{"path": "actual.txt"}])))
    assert session.evidence_revision == revision + 1


def test_investigation_coverage_uses_receipts_instead_of_note_claims():
    backend = brain.VisualDirectBackend({})
    backend.history = [{"role": "user", "content": [{"type": "text", "text": "I checked all history"}]}]
    for index in range(4):
        name = "desktop_history" if index >= 2 else "basic_search"
        result = ({"ok": True, "sources": ["recent"], "records": [], "next_offset": 12,
                   "coverage": [{"source": "recent", "ok": True}], "query": "narrow query"}
                  if index >= 2 else {"ok": True, "root": "C:/project", "matches": [], "truncated": True})
        backend.history.extend([
            {"role": "assistant", "content": [{"type": "tool_use", "id": str(index), "name": name}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": str(index),
                                          "is_error": index == 2,
                                          "content": [{"type": "text", "text": json.dumps(result)}]}]},
        ])
    fact = backend._investigation_fact()
    data = json.loads(fact.splitlines()[1])
    assert data["directory_searches"]["C:/project"] == {"calls": 2, "empty": 2, "truncated": 2}
    assert data["history_pages_read"] == 1
    assert data["latest_history_page"]["query"] == "narrow query"
    assert data["latest_history_page"]["next_offset"] == 12
    assert "I checked all history" not in fact


def test_resource_view_keeps_distinct_contexts_and_exact_event_view(monkeypatch):
    rows = [
        {"ts": "2026-10-11T20:00:00+08:00", "category": "browser", "url": "https://example.org/reading", "title": "reading", "type": "focus", "source": "backfill:tabbit"},
        {"ts": "2026-10-11T19:00:00+08:00", "category": "browser", "url": "https://example.org/reading", "title": "reading", "type": "focus", "source": "backfill:chrome"},
        {"ts": "2026-10-10T15:00:00+08:00", "category": "recent", "path": "C:/work/input.docx", "type": "file_open", "source": "backfill:recent"},
    ]
    monkeypatch.setattr(historyfacts, "collect", lambda days, sources: {
        "captured_at": 1, "days": days, "sources": sorted(sources), "coverage": [], "limitations": [], "records": rows})
    result = payload(historyfacts.query({"limit": 2}))
    assert result["view"] == "resources"
    assert result["total_matches"] == 2
    assert result["matched_events"] == 3
    assert result["next_offset"] is None
    assert result["records"][1]["path"] == "C:/work/input.docx"
    group = result["records"][0]
    assert group["occurrences"] == 2
    assert group["first_ts"] == rows[1]["ts"]
    assert group["last_ts"] == rows[0]["ts"]
    assert group["sources"] == ["backfill:tabbit", "backfill:chrome"]
    events = payload(historyfacts.query({"snapshot": result["snapshot"], "view": "events", "query": "reading", "limit": 2}))
    assert events["records"] == rows[:2]
    assert events["total_matches"] == 2


def test_resources_do_not_merge_different_urls_with_same_title(monkeypatch):
    snapshot = {"captured_at": 1, "days": 14, "sources": ["browser"], "coverage": [], "limitations": [], "records": [
        {"ts": "2026-10-11", "category": "browser", "url": "https://example.org/one", "title": "same"},
        {"ts": "2026-10-10", "category": "browser", "url": "https://example.org/two", "title": "same"}]}
    monkeypatch.setitem(historyfacts.SNAPSHOTS, "distinct-resources", snapshot)
    result = payload(historyfacts.query({"snapshot": "distinct-resources"}))
    assert result["total_matches"] == 2
    assert not historyfacts.query({"view": "unknown"}).success


def test_continuation_tracks_actual_tool_and_parameters_not_reworded_description():
    tracker = brain.ContinuationTracker()
    decision = {"next_step": {"status": "ready", "goal": "Understand the next work item", "action": "Read the next page",
                              "tool": "desktop_history", "arguments": {"snapshot": "stable", "offset": 15}}}
    first = tracker.pending(decision, 0)
    tracker.consume(first, 0)
    decision["next_step"]["action"] = "Continue looking for the missing requirement"
    assert tracker.pending(decision, 0) is None
    decision["next_step"]["arguments"]["offset"] = 30
    assert tracker.pending(decision, 0) is not None
    assert '"offset": 30' in brain.continuation_key(decision)


def test_unchanged_feed_keeps_original_snapshot_and_its_unread_pages(monkeypatch):
    monkeypatch.setattr(historyfacts, "SNAPSHOTS", {})
    rows = [{"category": "recent", "path": f"C:/work/item-{index}.txt", "ts": str(index)} for index in range(4)]
    monkeypatch.setattr(historyfacts, "collect", lambda days, sources: {
        "captured_at": 1, "days": days, "sources": sorted(sources), "records": rows, "coverage": [], "limitations": []})
    feed = historyfacts.HistoryFeed(SimpleNamespace(observe=lambda now: "metadata changed"))
    first = feed.observe(100)
    snapshot = json.loads(first.splitlines()[1])["snapshot"]
    for index in range(10):
        assert feed.observe(131 + index * 31) == ""
    assert json.loads(feed.context.splitlines()[1])["snapshot"] == snapshot
    reply = historyfacts.query({"snapshot": snapshot, "sources": ["recent"], "offset": 2})
    assert reply.success
    assert len(payload(reply)["records"]) == 2
    assert len(historyfacts.SNAPSHOTS) == 1


def test_feed_republishes_cursor_after_other_queries_evict_its_snapshot(monkeypatch):
    monkeypatch.setattr(historyfacts, "SNAPSHOTS", {})
    monkeypatch.setattr(historyfacts, "collect", lambda days, sources: {
        "captured_at": 1, "days": days, "sources": sorted(sources), "records": [], "coverage": [], "limitations": []})
    feed = historyfacts.HistoryFeed(SimpleNamespace(observe=lambda now: "metadata changed" if now == 100 else ""))
    original = json.loads(feed.observe(100).splitlines()[1])["snapshot"]
    for index in range(8):
        assert historyfacts.query({}).success
    assert original not in historyfacts.SNAPSHOTS
    renewed = feed.observe(131)
    assert renewed
    snapshot = json.loads(renewed.splitlines()[1])["snapshot"]
    assert snapshot != original
    assert historyfacts.query({"snapshot": snapshot}).success
    assert len(historyfacts.SNAPSHOTS) == 8


def test_feed_detects_changed_records_beyond_its_visible_sample(monkeypatch):
    monkeypatch.setattr(historyfacts, "SNAPSHOTS", {})
    rows = [{"category": "recent", "path": f"C:/work/item-{index}.txt", "ts": str(index)} for index in range(4)]
    monkeypatch.setattr(historyfacts, "collect", lambda days, sources: {
        "captured_at": 1, "days": days, "sources": sorted(sources), "records": list(rows), "coverage": [], "limitations": []})
    feed = historyfacts.HistoryFeed(SimpleNamespace(observe=lambda now: "metadata changed"))
    original = json.loads(feed.observe(100).splitlines()[1])["snapshot"]
    rows[3] = dict(rows[3], path="C:/work/new-result.txt")
    renewed = feed.observe(131)
    assert renewed
    snapshot = json.loads(renewed.splitlines()[1])["snapshot"]
    assert snapshot != original
    page = payload(historyfacts.query({"snapshot": snapshot, "sources": ["recent"], "offset": 2}))
    assert any(row["path"] == "C:/work/new-result.txt" for row in page["records"])
