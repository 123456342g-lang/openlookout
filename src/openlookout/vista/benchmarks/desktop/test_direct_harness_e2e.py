"""Scripted localhost model server for the direct harness, both protocols.

No live provider is contacted. The server answers only what each test scripts.
"""
from __future__ import annotations

import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from sprite.proactive import conversation, help as helpmod
from vista.benchmarks.desktop import brain, session as sessionmod
from vista.benchmarks.desktop.profiles import make_experiment, make_profile
from vista.core.contracts import Visual
from vista.core.profiles import Phase
from vista.core.runtime import TaskRuntime

PROTOCOLS = ("anthropic", "openai")


@pytest.fixture
def dialogue(tmp_path, monkeypatch):
    monkeypatch.setattr(helpmod, "DIR", tmp_path)
    monkeypatch.setattr(helpmod, "OFFER", tmp_path / "offer.json")
    monkeypatch.setattr(helpmod, "OFFER_LOG", tmp_path / "offers.jsonl")
    monkeypatch.setattr(sessionmod, "CURRENT", tmp_path / "current.json")
    monkeypatch.setattr(conversation, "history", lambda limit=80: [])
    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), "white").save(buffer, "JPEG")
    visual = Visual("screen", "test-screen", buffer.getvalue(), 320, 200, mime_type="image/jpeg")
    return sessionmod.DesktopSession("自然交流", {}, visual=visual)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode())
        except json.JSONDecodeError:
            body = {}
        self.server.seen.append({"path": self.path, "body": body})
        spec = self.server.script(self.server.seen)
        delay = spec.get("delay") or 0
        if delay:
            threading.Event().wait(delay)
        payload = spec.get("body", b"")
        if not isinstance(payload, (bytes, bytearray)):
            payload = json.dumps(payload).encode()
        try:
            self.send_response(int(spec.get("status", 200)))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, fmt, *args):
        return


class FakeModel(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, script):
        self.script = script
        self.seen = []
        super().__init__(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


def _quiet(protocol: str, *, text: str | None = None, arguments: str | dict | None = None,
           kind: str = "quiet", usage: dict | None = None, call_id: str = "c1") -> dict:
    if protocol == "openai":
        message: dict = {"content": text or ""}
        if arguments is not None:
            raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
            message["tool_calls"] = [{
                "id": call_id, "type": "function",
                "function": {"name": "companion", "arguments": raw},
            }]
        elif text is None:
            message["tool_calls"] = [{
                "id": call_id, "type": "function",
                "function": {"name": "companion", "arguments": json.dumps({"kind": kind})},
            }]
        body = {"choices": [{"finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                             "message": message}]}
        if usage:
            body["usage"] = usage
        return body
    if text is not None and arguments is None:
        content = [{"type": "text", "text": text}]
    else:
        payload = arguments if isinstance(arguments, dict) else {"kind": kind}
        content = [{"type": "tool_use", "id": call_id, "name": "companion", "input": payload}]
    body = {"content": content, "stop_reason": "tool_use" if arguments is not None or text is None else "end_turn"}
    if usage:
        body["usage"] = usage
    return body


def _cfg(server: FakeModel, protocol: str) -> dict:
    return {"model": "fake", "base_url": server.url, "api_key": "synthetic-harness-key", "protocol": protocol}


def _backend(dialogue, tmp_path, server, protocol, *, name="artifacts"):
    experiment = make_experiment(make_profile(), backend="claude", model="fake", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / name)
    backend = brain.VisualDirectBackend(_cfg(server, protocol), runtime)
    backend.attach(dialogue)
    return runtime, backend


def _no_backoff(monkeypatch):
    monkeypatch.setattr(brain.time, "sleep", lambda _seconds: None)


def _has_image(body: dict, protocol: str) -> bool:
    raw = json.dumps(body)
    if protocol == "openai":
        return "image_url" in raw
    return '"type": "image"' in raw


def _tool_text(body: dict, protocol: str) -> str:
    if protocol == "openai":
        return "\n".join(str(message.get("content") or "")
                         for message in body.get("messages", []) if message.get("role") == "tool")
    parts = []
    for message in body.get("messages", []):
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                parts.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(parts)


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("status", (500, 502, 503))
def test_transient_http_retries_then_succeeds(dialogue, tmp_path, monkeypatch, protocol, status):
    _no_backoff(monkeypatch)
    sleeps = []
    monkeypatch.setattr(brain.time, "sleep", lambda seconds: sleeps.append(seconds))

    def script(seen):
        if len(seen) <= 2:
            return {"status": status, "body": {"error": "down"}}
        return {"body": _quiet(protocol)}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="transient"))
        assert reply.boundary == "decision_complete"
        assert len(server.seen) == 3
        assert sleeps == list(brain.RATE_LIMIT_BACKOFF_S)
        assert server.seen[0]["path"].endswith("/messages" if protocol == "anthropic" else "/chat/completions")
    finally:
        runtime.close()
        server.stop()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_bad_json_retries_then_succeeds(dialogue, tmp_path, monkeypatch, protocol):
    sleeps = []
    monkeypatch.setattr(brain.time, "sleep", lambda seconds: sleeps.append(seconds))

    def script(seen):
        if len(seen) <= 2:
            return {"body": b"not-json"}
        return {"body": _quiet(protocol)}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="bad-json"))
        assert reply.boundary == "decision_complete"
        assert len(server.seen) == 3
        assert sleeps == list(brain.RATE_LIMIT_BACKOFF_S)
    finally:
        runtime.close()
        server.stop()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_timeout_retries_then_succeeds(dialogue, tmp_path, monkeypatch, protocol):
    monkeypatch.setattr(brain, "MODEL_HTTP_TIMEOUT_S", 0.3)
    monkeypatch.setattr(brain.time, "sleep", lambda _seconds: None)

    def script(seen):
        if len(seen) <= 2:
            return {"delay": 2.0, "body": _quiet(protocol)}
        return {"body": _quiet(protocol)}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="timeout"))
        assert reply.boundary == "decision_complete"
        assert len(server.seen) == 3
    finally:
        runtime.close()
        server.stop()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_final_failure_keeps_the_turn_and_writes_history(dialogue, tmp_path, monkeypatch, protocol):
    _no_backoff(monkeypatch)

    def script(seen):
        return {"status": 500, "body": {"error": "still-down"}}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    history_path = tmp_path / "direct_history.json"
    backend.history_file = history_path
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="KEEP-THIS-TURN"))
        assert reply.returncode == 1
        assert len(server.seen) == 3
        assert any("KEEP-THIS-TURN" in json.dumps(message, ensure_ascii=False) for message in backend.history)
        saved = json.loads(history_path.read_text(encoding="utf-8"))
        assert "KEEP-THIS-TURN" in json.dumps(saved, ensure_ascii=False)
        assert "synthetic-harness-key" not in history_path.read_text(encoding="utf-8")
        resumed = brain.VisualDirectBackend(_cfg(server, protocol), runtime)
        resumed.history_file = history_path
        resumed._load_history()
        assert any("KEEP-THIS-TURN" in json.dumps(message, ensure_ascii=False) for message in resumed.history)
    finally:
        runtime.close()
        server.stop()


def test_legacy_backend_keeps_the_prompt_when_the_call_fails(monkeypatch):
    def fail(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    monkeypatch.setattr(brain.time, "sleep", lambda _seconds: None)
    backend = brain._LegacyDirectBackend(
        {"model": "m", "base_url": "https://model.example", "api_key": "k", "protocol": "anthropic"})
    reply = backend.run(type("Task", (), {"public_text": "keep-this-prompt"})())
    assert reply.final_message == ""
    assert backend.history[0]["content"] == "keep-this-prompt"


def test_429_retries_stop_at_the_call_cap(monkeypatch):
    calls = []

    def fail(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError("https://example.test", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    budget = brain.TurnCallBudget(2)
    with pytest.raises(brain.ModelCallBudgetExhausted):
        brain.model_response(object(), sleep=lambda _seconds: None, budget=budget)
    assert len(calls) == 2
    assert budget.used == 2


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_429_cap_on_the_fake_server_keeps_history(dialogue, tmp_path, monkeypatch, protocol):
    _no_backoff(monkeypatch)

    def script(seen):
        return {"status": 429, "body": {"error": "slow down"}}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    backend.max_segments = 1
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="RATE-TURN"))
        assert reply.returncode == 1
        assert len(server.seen) == 2
        assert any("RATE-TURN" in json.dumps(message, ensure_ascii=False) for message in backend.history)
    finally:
        runtime.close()
        server.stop()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_bad_companion_arguments_name_the_field(dialogue, tmp_path, monkeypatch, protocol):
    _no_backoff(monkeypatch)

    def script(seen):
        if len(seen) == 1:
            return {"body": _quiet(protocol, arguments={"kind": "nope"}, call_id="bad-kind")}
        return {"body": _quiet(protocol, call_id=f"quiet-{len(seen)}")}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="validate"))
        assert reply.boundary == "decision_complete"
        assert len(server.seen) >= 2
        detail = _tool_text(server.seen[1]["body"], protocol)
        assert "Invalid tool arguments" in detail
        assert "kind" in detail
        assert "schema" in detail
        assert "enum" in detail
    finally:
        runtime.close()
        server.stop()


def test_openai_bad_json_arguments_are_a_parse_error(dialogue, tmp_path, monkeypatch):
    _no_backoff(monkeypatch)

    def script(seen):
        if len(seen) == 1:
            return {"body": _quiet("openai", arguments="{", call_id="bad-json")}
        return {"body": _quiet("openai", call_id="quiet-2")}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, "openai")
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="parse"))
        assert reply.boundary == "decision_complete"
        detail = _tool_text(server.seen[1]["body"], "openai")
        assert "Could not parse tool arguments as JSON" in detail
        assert '"raw"' not in json.dumps(server.seen[1]["body"])
    finally:
        runtime.close()
        server.stop()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_forced_companion_gets_one_repair(dialogue, tmp_path, monkeypatch, protocol):
    _no_backoff(monkeypatch)

    def script(seen):
        if len(seen) == 1:
            return {"body": _quiet(protocol, text="only words", call_id="words")}
        return {"body": _quiet(protocol, call_id="repair")}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    backend.max_segments = 0
    before = len(dialogue.decisions)
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="repair"))
        assert len(server.seen) == 2
        assert reply.boundary == "decision_complete"
        assert len(dialogue.decisions) == before + 1
    finally:
        runtime.close()
        server.stop()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_first_request_includes_the_screenshot_and_later_text_turns_do_not(dialogue, tmp_path, monkeypatch, protocol):
    _no_backoff(monkeypatch)

    def script(seen):
        return {"body": _quiet(protocol, call_id=f"shot-{len(seen)}")}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    backend.turn_without_visual = True
    try:
        first = backend.run(runtime.prepare_input(Phase.STEP, public_text="opening", observation=None))
        assert first.boundary == "decision_complete"
        assert _has_image(server.seen[0]["body"], protocol)
        assert "source_id=test-screen" in json.dumps(server.seen[0]["body"])
        count = len(server.seen)
        backend.turn_without_visual = True
        second = backend.run(runtime.prepare_input(Phase.STEP, public_text="later", observation=None))
        assert second.boundary == "decision_complete"
        assert not _has_image(server.seen[count]["body"], protocol)
    finally:
        runtime.close()
        server.stop()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_usage_lands_in_model_usage(dialogue, tmp_path, monkeypatch, protocol):
    _no_backoff(monkeypatch)
    if protocol == "openai":
        usage = {"prompt_tokens": 11, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 7}}
        expect_cache = 7
    else:
        usage = {"input_tokens": 11, "output_tokens": 2, "cache_read_input_tokens": 4,
                 "cache_creation_input_tokens": 1}
        expect_cache = 4

    def script(seen):
        return {"body": _quiet(protocol, usage=usage)}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol)
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="usage"))
        assert reply.boundary == "decision_complete"
        rows = [json.loads(line) for line in (tmp_path / "artifacts" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        recorded = [row for row in rows if row.get("event") == "model_usage"][-1]
        assert recorded["input_tokens"] == 11
        assert recorded["output_tokens"] == 2
        assert recorded["cache_read_input_tokens"] == expect_cache
    finally:
        runtime.close()
        server.stop()


def test_openai_request_merges_consecutive_user_messages(dialogue, tmp_path, monkeypatch):
    _no_backoff(monkeypatch)

    def script(seen):
        return {"body": _quiet("openai")}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, "openai")
    backend.history_context = "HISTORY-FACT-MARKER"
    try:
        backend.run(runtime.prepare_input(Phase.INITIAL, public_text="OPENING-TEXT"))
        messages = server.seen[0]["body"]["messages"]
        roles = [message["role"] for message in messages]
        assert all(not (left == "user" and right == "user") for left, right in zip(roles, roles[1:]))
        raw = json.dumps(messages, ensure_ascii=False)
        assert "HISTORY-FACT-MARKER" in raw
        assert "OPENING-TEXT" in raw
    finally:
        runtime.close()
        server.stop()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_restart_resumes_saved_history(dialogue, tmp_path, monkeypatch, protocol):
    _no_backoff(monkeypatch)

    def script(seen):
        return {"body": _quiet(protocol)}

    server = FakeModel(script)
    runtime, backend = _backend(dialogue, tmp_path, server, protocol, name="artifacts-a")
    history_path = tmp_path / "direct_history.json"
    backend.history_file = history_path
    try:
        first = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="RESUME-MARKER"))
        assert first.boundary == "decision_complete"
        runtime2_dir = tmp_path / "artifacts-b"
        experiment = make_experiment(make_profile(), backend="claude", model="fake", effort="low",
                                     revision="test", presentation={})
        runtime2 = TaskRuntime(dialogue, experiment, artifact_dir=runtime2_dir)
        resumed = brain.VisualDirectBackend(_cfg(server, protocol), runtime2)
        resumed.history_file = history_path
        resumed.attach(dialogue)
        count = len(server.seen)
        second = resumed.run(runtime2.prepare_input(Phase.STEP, public_text="next"))
        assert second.returncode in {0, 1}
        raw = json.dumps(server.seen[count]["body"], ensure_ascii=False)
        assert "RESUME-MARKER" in raw
        assert resumed._screen_sent is True
    finally:
        runtime.close()
        server.stop()
