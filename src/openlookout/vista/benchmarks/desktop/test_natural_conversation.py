from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from sprite.proactive import conversation, help as helpmod
from vista.benchmarks.desktop import actions, brain, session as sessionmod
from vista.benchmarks.desktop.profiles import make_experiment, make_profile
from vista.core.contracts import Visual
from vista.core.profiles import Phase
from vista.core.runtime import TaskRuntime


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


def test_same_topic_can_continue_without_a_time_gate(dialogue):
    first = {"kind": "companion", "say": "这段把直觉和证据分开了，我觉得挺有意思。", "topic": "阅读讨论"}
    second = dict(first, say="它后面那个反例，你觉得能推翻前面的说法吗？")
    dialogue._companion(first)
    dialogue._companion(second)
    assert dialogue.reports == [first["say"], second["say"]]
    dialogue._companion(second)
    assert dialogue.suppressed == 1


def test_synthetic_longitudinal_trace_lets_model_choose_chat_or_quiet(dialogue, tmp_path, monkeypatch):
    """No scene allowlist: across two turns the model may chat, then stay quiet
    while retaining a concrete background continuation.

    The trace is synthetic and isolated; it exercises the same companion
    contract used by the Claude transport without reading user history or
    enabling host execution.
    """
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example",
                                         "api_key": "test"}, runtime)
    calls = []

    def respond(request, timeout):
        calls.append(json.loads(request.data))
        if len(calls) == 1:
            tool = {"type": "tool_use", "id": "chat", "name": "companion", "input": {
                "kind": "companion", "intent": "conversation",
                "say": "这个思路的转折挺有意思。", "topic": "synthetic-trace"}}
        else:
            tool = {"type": "tool_use", "id": "quiet", "name": "companion", "input": {
                "kind": "quiet", "intent": "outcome",
                "next_step": {"status": "ready", "goal": "核对一个关键缺口",
                               "action": "读取对应资料并独立核验", "evidence": "合成观察"}}}
        return Response({"content": [tool], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        first = backend.run(runtime.prepare_input(Phase.INITIAL))
        second = backend.run(runtime.prepare_input(Phase.STEP))
        assert first.boundary == second.boundary == "decision_complete"
        assert dialogue.reports == ["这个思路的转折挺有意思。"]
        assert dialogue.decisions[-1]["kind"] == "quiet"
        assert dialogue.decisions[-1]["next_step"]["status"] == "ready"
        assert dialogue.decisions[-1]["next_step"]["action"]
    finally:
        runtime.close()


def test_background_trim_does_not_swallow_unrelated_chat(dialogue):
    dialogue._turn_mutations.append({"tool": "desktop_trim", "success": True})
    dialogue._companion({"kind": "companion", "intent": "conversation", "say": "这个想法和刚才那段有个联系。"})
    assert dialogue.reports == ["这个想法和刚才那段有个联系。"]


def test_background_maintenance_and_chat_preserve_ready_work(dialogue):
    from vista.core.contracts import ToolReply

    reply = dialogue._handler("desktop_trim", lambda args: ToolReply("后台闲置页已归还"))({"pid": 123})
    assert reply.success
    step = {"status": "ready", "goal": "核对用户工作中的缺口", "action": "读取线索对应的资料", "evidence": "真实历史中的文件路径"}
    dialogue._companion({"kind": "companion", "intent": "conversation", "say": "这段的反例挺有意思。", "next_step": step})
    assert dialogue.reports == ["这段的反例挺有意思。"]
    assert dialogue.action_results[-1]["tool"] == "desktop_trim"
    assert dialogue.decisions[-1]["next_step"] == step
    assert brain.continuation_key(dialogue.decisions[-1]) is not None


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_vista_inspection_images_reach_model_before_dialogue(dialogue, tmp_path, monkeypatch):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    requests = []
    message = "这个解释有个有趣的地方：它把观察和判断分开了，你会怎么划这条线？"

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        if len(requests) == 1:
            call = {"type": "tool_use", "id": "inspect-1", "name": "inspect", "input": {
                "question": "看清这段文字", "views": [{"event": 0, "label": "paragraph",
                    "region": {"x": 0, "y": 0, "width": 120, "height": 100}}]}}
        else:
            call = {"type": "tool_use", "id": "chat-1", "name": "companion", "input": {
                "kind": "companion", "intent": "conversation", "say": message, "topic": "观点讨论"}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        result = backend.run(runtime.prepare_input(Phase.INITIAL))
        delivered = requests[1]["messages"][-1]["content"][0]["content"]
        assert any(block["type"] == "image" for block in delivered)
        assert any("paragraph" in block.get("text", "") for block in delivered)
        assert result.boundary == "decision_complete"
        assert json.loads(helpmod.OFFER.read_text(encoding="utf-8"))["text"] == message
    finally:
        runtime.close()


def test_saved_evidence_pixels_are_returned_for_review_before_reporting(dialogue, tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: Image.new("RGB", (320, 200), "white"))
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    requests = []
    evidence_id = None

    def respond(request, timeout):
        nonlocal evidence_id
        body = json.loads(request.data)
        requests.append(body)
        if len(requests) == 1:
            assert any("source_id=test-screen" in block.get("text", "")
                       for message in body["messages"] for block in message["content"])
            call = {"type": "tool_use", "id": "capture", "name": "desktop_capture_evidence", "input": {
                "label": "实验输出", "purpose": "要求二：显示结果及单位", "source_id": "test-screen",
                "region": {"x": 20, "y": 30, "width": 160, "height": 100}}}
        elif len(requests) == 2:
            result = body["messages"][-1]["content"][0]["content"]
            assert any(block["type"] == "image" and block["source"]["media_type"] == "image/png" for block in result)
            evidence_id = json.loads(result[0]["text"])["id"]
            call = {"type": "tool_use", "id": "review", "name": "desktop_review_evidence", "input": {
                "id": evidence_id, "checks": {"relevant": False, "complete": False, "legible": True, "focused": True},
                "reason": "图中只有空白，没有要求的实验输出或单位"}}
        else:
            result = json.loads(body["messages"][-1]["content"][0]["content"][0]["text"])
            assert result["status"] == "rejected"
            call = {"type": "tool_use", "id": "finish", "name": "companion", "input": {
                "kind": "quiet", "next_step": {"status": "waiting", "goal": "取得要求二的证据",
                "action": "等待实验结果实际显示后重新定位", "evidence": "截图为空白，核验未通过"}}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        result = backend.run(runtime.prepare_input(Phase.INITIAL))
        assert result.boundary == "decision_complete"
        assert len(requests) == 3
        assert dialogue.actions == 0
        assert dialogue.reports == []
        assert json.loads((actions.EVIDENCE_DIR / f"{evidence_id}.json").read_text(encoding="utf-8"))["status"] == "rejected"
    finally:
        runtime.close()


def test_chat_context_includes_actual_dialogue_during_work(monkeypatch):
    monkeypatch.setattr(conversation, "history", lambda limit=80: [
        {"role": "assistant", "text": "先前提出的观点", "t": 100},
        {"role": "user", "text": "我不这么想", "t": 101},
    ])
    text = brain.conversation_fact(idle_s=0, now=102)
    assert "先前提出的观点" in text and "我不这么想" in text
    assert "工作进行中也可以聊" in text


def test_research_does_not_consume_mutating_action_budget(dialogue):
    reply = dialogue._handler("basic_web_search", lambda args: actions.ToolReply("公共线索"))({"query": "public topic"})
    assert reply.success
    assert dialogue.actions == 0 and dialogue.action_results == []


def test_public_search_failure_does_not_invent_facts(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("ddgs.DDGS", fail)
    reply = actions.basic_web_search({"query": "public topic"})
    assert not reply.success
    assert "results" not in json.loads(reply.text)


def test_unanswered_opening_is_not_evidence_of_interest(monkeypatch):
    monkeypatch.setattr(conversation, "history", lambda limit=80: [
        {"role": "assistant", "text": "我查到了人物生平的另一种说法", "t": 100},
    ])
    text = brain.conversation_fact(idle_s=0, now=102)
    assert "没有回应不等于拒绝" in text
    assert "不证明他对你引入的枝节感兴趣" in text


def test_search_sends_only_public_query_not_private_relevance(monkeypatch):
    queries = []

    class PublicSearch:
        def __init__(self, **kwargs):
            pass

        def text(self, query, **kwargs):
            queries.append(query)
            return [{"title": "Public source", "href": "https://example.org/topic", "body": "Public evidence"}]

    monkeypatch.setattr("ddgs.DDGS", PublicSearch)
    reply = actions.basic_web_search({"query": "public concept",
                                      "purpose": "local private context",
                                      "enough_when": "local evidence gap"})
    assert queries == ["public concept"]
    data = json.loads(reply.text)
    assert data["purpose"] == "local private context"
    assert data["enough_when"] == "local evidence gap"


def test_chat_message_waits_for_a_real_answer(tmp_path, monkeypatch):
    from sprite.proactive import live, feedback

    monkeypatch.setattr(conversation, "LOG", tmp_path / "conversation.jsonl")
    monkeypatch.setattr(feedback, "DIR", tmp_path)
    monkeypatch.setattr(feedback, "FB_LOG", tmp_path / "feedback.jsonl")
    monkeypatch.setattr(feedback, "ACT_LOG", tmp_path / "activity.log")
    monkeypatch.setattr(live, "read_current", lambda: {"activity": "读书"})
    assert live.queue_message("你这么觉得的理由是什么") == ""
    rows = conversation._read(conversation.LOG)
    assert len(rows) == 1 and rows[0]["role"] == "user"
    assert rows[0]["text"] == "你这么觉得的理由是什么"
    assert feedback.recent_feedback()[0]["text"] == rows[0]["text"]


def test_changed_scene_rejects_stale_action_and_then_answers(dialogue, tmp_path, monkeypatch):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    initial = brain.ScreenSample(1, dialogue.task.observation.displayed_observations[0].views[0],
                                 [0] * 1440, ("reader", "book"), 100, 0)
    updated = brain.ScreenSample(2, initial.visual, [255] * 1440, ("editor", "project"), 101, 0)

    class Screens:
        current = initial

        def latest(self):
            return self.current

    screens = Screens()
    backend.live_screen = screens
    backend.screen_sample = initial
    backend.screen_revision = initial.revision
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        if len(requests) == 1:
            screens.current = updated
            call = {"type": "tool_use", "id": "stale-trim", "name": "desktop_trim", "input": {"pid": 1234}}
        else:
            assert any(block.get("type") == "image"
                       for message in requests[1]["messages"]
                       for block in message.get("content", []))
            assert "现场更新" in requests[1]["messages"][-1]["content"][-1]["text"]
            call = {"type": "tool_use", "id": "new-chat", "name": "companion", "input": {
                "kind": "companion", "intent": "conversation", "say": "先把最影响结果的那一步做通，后面才值得优化。"}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    monkeypatch.setattr(brain, "new_feedback", lambda since: "")
    monkeypatch.setattr(brain, "conversation_fact", lambda **kwargs: "")
    monkeypatch.setattr(brain.watching, "idle_seconds", lambda: 0)
    try:
        result = backend.run(runtime.prepare_input(Phase.INITIAL))
        assert result.boundary == "decision_complete"
        assert dialogue.actions == 0
        assert len(dialogue.reports) == 1
        assert backend.screen_revision == 2
        rejection = requests[1]["messages"][-2]["content"][0]
        assert rejection["is_error"] and rejection["tool_use_id"] == "stale-trim"
    finally:
        runtime.close()


def test_plain_text_is_not_mistaken_for_delivered_dialogue(dialogue, tmp_path, monkeypatch):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    requests = []

    def respond(request, timeout):
        requests.append(json.loads(request.data))
        blocks = ([{"type": "text", "text": "未完成的内部思考"}] if len(requests) == 1 else
                  [{"type": "tool_use", "id": "finish", "name": "companion", "input": {"kind": "quiet"}}])
        return Response({"content": blocks, "stop_reason": "max_tokens" if len(requests) == 1 else "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        result = backend.run(runtime.prepare_input(Phase.INITIAL))
        assert result.boundary == "decision_complete"
        assert "立即调用 companion" in requests[1]["messages"][-1]["content"][0]["text"]
        assert dialogue.reports == []
    finally:
        runtime.close()


@pytest.mark.parametrize("feedback_changed", [False, True])
def test_reclaim_uses_file_facts_but_still_respects_new_feedback(dialogue, tmp_path, monkeypatch, feedback_changed):
    from vista.core.contracts import ToolBinding, ToolReply

    executed = []

    def reclaim_stub(arguments):
        executed.append(arguments)
        return ToolReply("simulated reclaim result")

    dialogue.tools = tuple(
        ToolBinding(binding.spec, reclaim_stub) if binding.spec.name == "desktop_reclaim" else binding
        for binding in dialogue.tools
    )
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    initial = brain.ScreenSample(1, dialogue.current_visual, [0] * 1440, ("reader", "book"), 100, 0)
    updated = brain.ScreenSample(2, initial.visual, [255] * 1440, ("editor", "project"),
                                 101, int(feedback_changed))

    class Screens:
        current = initial

        def latest(self):
            return self.current

    screens = Screens()
    backend.live_screen = screens
    backend.screen_sample = initial
    backend.screen_revision = initial.revision
    requests = []

    def respond(request, timeout):
        requests.append(json.loads(request.data))
        if len(requests) == 1:
            screens.current = updated
            call = {"type": "tool_use", "id": "reclaim", "name": "desktop_reclaim", "input": {"exhaustive": True}}
        else:
            call = {"type": "tool_use", "id": "finish", "name": "companion", "input": {"kind": "quiet"}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    monkeypatch.setattr(brain, "new_feedback", lambda since: "")
    monkeypatch.setattr(brain, "conversation_fact", lambda **kwargs: "")
    monkeypatch.setattr(brain.watching, "idle_seconds", lambda: 0)
    try:
        assert backend.run(runtime.prepare_input(Phase.INITIAL)).boundary == "decision_complete"
        assert executed == ([] if feedback_changed else [{"exhaustive": True}])
        replies = [block for message in requests[1]["messages"] for block in message["content"]
                   if block.get("type") == "tool_result" and block.get("tool_use_id") == "reclaim"]
        assert len(replies) == 1
        assert replies[0]["is_error"] == feedback_changed
    finally:
        runtime.close()


def test_read_only_investigation_is_forced_to_report(dialogue, tmp_path, monkeypatch):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        index = len(requests)
        if index <= 3:
            call = {"type": "tool_use", "id": f"search-{index}", "name": "basic_time", "input": {}}
        else:
            call = {"type": "tool_use", "id": "finish", "name": "companion", "input": {
                "kind": "companion", "intent": "outcome", "say": "我核对过了，下一步先验证最影响结果的那一项。",
                "next_step": {"status": "ready", "goal": "验证关键假设", "action": "做一次最小验证", "evidence": "只读调查已足够"}}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        result = backend.run(runtime.prepare_input(Phase.INITIAL))
        assert result.boundary == "decision_complete"
        assert len(requests) == 4
        assert requests[3]["tool_choice"] == {"type": "tool", "name": "companion"}
        assert len(dialogue.reports) == 1
    finally:
        runtime.close()


def test_ready_continuation_reports_after_one_validation(dialogue, tmp_path, monkeypatch):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        if len(requests) == 1:
            call = {"type": "tool_use", "id": "validate", "name": "basic_time", "input": {}}
        else:
            call = {"type": "tool_use", "id": "finish", "name": "companion", "input": {
                "kind": "quiet", "next_step": {"status": "done", "goal": "核对计划", "action": "已完成最小验证", "evidence": "验证结果已记录"}}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        result = backend.run(runtime.prepare_input(Phase.STEP, public_text="【续办】执行上轮计划：只做最小验证。"))
        assert result.boundary == "decision_complete"
        assert requests[1]["tool_choice"] == {"type": "tool", "name": "companion"}
    finally:
        runtime.close()


def test_decision_evidence_is_local_not_user_facing(dialogue):
    decision = {"goal": "完成报告", "evidence": "连续两次返工", "uncertainty": "可能是正常修订",
                "choice": "核对缺失信息", "expected_outcome": "减少再次返工", "observed_outcome": "待验证"}
    dialogue._companion({"kind": "quiet", "decision": decision})
    row = json.loads((sessionmod.CURRENT.parent / "decisions.jsonl").read_text(encoding="utf-8"))
    assert row["decision"] == decision
    assert dialogue.reports == []


def test_transport_window_preserves_tool_use_pairs():
    backend = brain.VisualDirectBackend({})
    backend.history = [{"role": "user", "content": [{"type": "text", "text": "CURRENT"}]}]
    for index in range(14):
        backend.history.extend([
            {"role": "assistant", "content": [{"type": "tool_use", "id": f"call-{index}"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"call-{index}"}]},
        ])
    messages = backend._messages()
    assert messages[-1] == backend.history[-1]
    for index, message in enumerate(messages):
        if message["role"] == "assistant":
            calls = [block.get("id") for block in message["content"] if block.get("type") == "tool_use"]
            if calls:
                result = messages[index + 1]
                assert result["role"] == "user"
                assert {block.get("tool_use_id") for block in result["content"]} >= set(calls)


def test_each_request_has_one_current_execution_snapshot(dialogue, tmp_path, monkeypatch):
    from vista.benchmarks.desktop.agenda import Agenda
    from vista.benchmarks.desktop.decision_engine import DecisionEngine

    dialogue.agenda = Agenda(DecisionEngine())
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    requests = []

    def respond(request, timeout):
        requests.append(json.loads(request.data))
        return Response({"content": [{"type": "tool_use", "id": f"finish-{len(requests)}", "name": "companion",
                                      "input": {"kind": "quiet"}}], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        for phase in (Phase.INITIAL, Phase.STEP):
            dialogue.agenda.update([{
                "goal_id": "lookup", "goal": f"Find evidence in {phase.value}", "lane": "investigate",
                "evidence": ["A real resource was opened"], "expected": "Find the relevant requirement",
                "state": "waiting", "waiting_on": "External source is unavailable",
                "estimates": {"confidence": 0.5},
            }], set())
            snapshot = dialogue.agenda.context()
            result = backend.run(runtime.prepare_input(phase, public_text="Fresh observation\n" + snapshot))
            assert result.boundary == "decision_complete"
            text_blocks = [block.get("text", "") for message in requests[-1]["messages"] for block in message["content"]]
            assert sum(text.count("【执行进度，不是探索方向】") for text in text_blocks) == 1
            assert snapshot in text_blocks
            assert any("Fresh observation" in text for text in text_blocks)
    finally:
        runtime.close()


def test_operation_records_reach_model_before_any_tool_call(dialogue, tmp_path, monkeypatch):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    backend.history_context = "actual-record: browser visit, file opened, result unknown"
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        assert any(backend.history_context in block.get("text", "")
                   for message in body["messages"] for block in message["content"])
        return Response({"content": [{"type": "tool_use", "id": "finish", "name": "companion",
                                      "input": {"kind": "quiet"}}], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        assert backend.run(runtime.prepare_input(Phase.INITIAL)).boundary == "decision_complete"
        assert len(requests) == 1
    finally:
        runtime.close()


def test_ordinary_refresh_allows_evidence_backed_chat_without_timing_trigger(dialogue, tmp_path, monkeypatch):
    """A normal screen refresh must tell the model that relevant conversation
    is allowed; it must not force status-only quiet behavior."""
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        return Response({"content": [{"type": "tool_use", "id": "finish", "name": "companion",
                                       "input": {"kind": "companion", "intent": "conversation",
                                                  "say": "这个思路和刚才的证据有个联系。"}}],
                         "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        result = backend.run(runtime.prepare_input(Phase.STEP, public_text="普通画面刷新"))
        assert result.boundary == "decision_complete"
        prompt = "\n".join(block.get("text", "") for msg in requests[0]["messages"] for block in msg["content"])
        assert "evidence-backed" in prompt
        assert "status broadcast" in prompt
        assert dialogue.reports == ["这个思路和刚才的证据有个联系。"]
    finally:
        runtime.close()


def test_new_history_context_reopens_probe_without_repeating_same_context(dialogue, tmp_path, monkeypatch):
    from vista.benchmarks.desktop.agenda import Agenda
    from vista.benchmarks.desktop.decision_engine import DecisionEngine
    from vista.core.contracts import ToolBinding, ToolReply

    dialogue.agenda = Agenda(DecisionEngine())
    dialogue.tools = tuple(ToolBinding(binding.spec, lambda arguments: ToolReply(json.dumps({"ok": True, "records": [], "next_offset": None})))
                           if binding.spec.name == "desktop_history" else binding for binding in dialogue.tools)
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low", revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        probing = body["tool_choice"] == {"type": "tool", "name": "desktop_history"}
        call = {"type": "tool_use", "id": f"call-{len(requests)}", "name": "desktop_history" if probing else "companion",
                "input": {} if probing else {"kind": "quiet"}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    monkeypatch.setattr(brain, "residual_fact", lambda **kwargs: "")
    monkeypatch.setattr(brain, "long_term_fact", lambda **kwargs: "")
    try:
        backend.history_context = "real-source-version-1"
        backend.run(runtime.prepare_input(Phase.INITIAL))
        count = len(requests)
        backend.run(runtime.prepare_input(Phase.STEP))
        assert requests[count]["tool_choice"] == {"type": "any"}
        backend.history_context = "real-source-version-2"
        backend.run(runtime.prepare_input(Phase.STEP, public_text="【续办】读取旧快照下一页"))
        count = len(requests)
        backend.run(runtime.prepare_input(Phase.STEP))
        assert requests[count]["tool_choice"] == {"type": "tool", "name": "desktop_history"}
    finally:
        runtime.close()


def test_old_snapshot_read_cannot_mark_new_history_context_as_explored(dialogue, tmp_path, monkeypatch):
    from vista.benchmarks.desktop.agenda import Agenda
    from vista.benchmarks.desktop.decision_engine import DecisionEngine
    from vista.core.contracts import ToolBinding, ToolReply

    dialogue.agenda = Agenda(DecisionEngine())
    dialogue.tools = tuple(ToolBinding(binding.spec, lambda arguments: ToolReply(json.dumps({"ok": True, "snapshot": "old", "records": []})))
                           if binding.spec.name == "desktop_history" else binding for binding in dialogue.tools)
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low", revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    backend.history_context = '【真实操作记录小页】\n{"snapshot":"new"}'
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        call = ({"type": "tool_use", "id": "old-page", "name": "desktop_history", "input": {"snapshot": "old", "offset": 15}}
                if len(requests) == 1 else {"type": "tool_use", "id": f"finish-{len(requests)}", "name": "companion", "input": {"kind": "quiet"}})
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    monkeypatch.setattr(brain, "residual_fact", lambda **kwargs: "")
    monkeypatch.setattr(brain, "long_term_fact", lambda **kwargs: "")
    try:
        backend.run(runtime.prepare_input(Phase.STEP, public_text="【续办】读取旧页"))
        assert backend.opportunity_probe_context != backend.history_context
        count = len(requests)
        backend.run(runtime.prepare_input(Phase.STEP))
        assert requests[count]["tool_choice"] == {"type": "tool", "name": "desktop_history"}
    finally:
        runtime.close()


def test_history_window_keeps_current_and_previous_plain_turn_only():
    backend = brain.VisualDirectBackend({})
    backend.history = []
    for index in range(6):
        backend.history.extend([
            {"role": "user", "content": [{"type": "text", "text": f"turn-{index}"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": f"call-{index}"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"call-{index}"}]},
        ])
    messages = backend._messages()
    assert messages[0]["content"][0]["text"] == "turn-4"
    assert messages[-1]["content"][0]["tool_use_id"] == "call-5"
    assert len(messages) <= 6


def test_scene_updates_preserve_active_turn_evidence(dialogue, tmp_path):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({}, runtime)
    try:
        backend._append_input(runtime.prepare_input(Phase.INITIAL))
        backend.history.extend([
            {"role": "assistant", "content": [{"type": "tool_use", "id": "source-1",
                                               "name": "desktop_read_local", "input": {"path": "source.txt"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "source-1",
                                          "content": [{"type": "text", "text": "actual source evidence"}]}]},
        ])
        for index in range(20):
            backend._append_input(runtime.prepare_input(Phase.STEP, public_text=f"scene-{index}"),
                                  scene_update=True)
        backend.history.append({"role": "user", "content": [{"type": "text", "text": "finish with companion"}]})
        messages = backend._messages()
        assert any(block.get("tool_use_id") == "source-1"
                   for message in messages for block in message["content"])
        assert sum(block.get("type") == "image"
                   for message in messages for block in message["content"]) == 1
        assert messages[-1]["content"][0]["text"] == "finish with companion"
        backend._append_input(runtime.prepare_input(Phase.STEP, public_text="next decision"))
        assert len(backend._messages()) <= 16
    finally:
        runtime.close()


def test_transport_retries_disconnect_without_changing_request(monkeypatch):
    import http.client
    import urllib.request

    request = urllib.request.Request("https://model.example", data=b"same body")
    requests = []

    def respond(current, timeout):
        requests.append(current)
        if len(requests) == 1:
            raise http.client.RemoteDisconnected("remote closed")
        return Response({"content": []})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    assert brain.model_response(request) == {"content": []}
    assert requests == [request, request]


def test_transport_stops_after_repeated_disconnect(monkeypatch):
    import http.client

    attempts = []

    def disconnect(request, timeout):
        attempts.append(request)
        raise http.client.RemoteDisconnected("remote closed")

    monkeypatch.setattr("urllib.request.urlopen", disconnect)
    with pytest.raises(http.client.RemoteDisconnected):
        brain.model_response(object())
    assert len(attempts) == 2


def test_repeated_refused_actions_finish_without_claiming_progress(dialogue, tmp_path, monkeypatch):
    from vista.core.contracts import ToolBinding, ToolReply

    dialogue.tools = tuple(
        ToolBinding(binding.spec, dialogue._handler("desktop_trim", lambda args: ToolReply("protected process", success=False)))
        if binding.spec.name == "desktop_trim" else binding for binding in dialogue.tools)
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    # The live default stops a turn after a handful of HTTP calls. This test
    # is about repeated refusals, so give the streak room to finish on its own.
    backend.max_segments = 12
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        finish = body["tool_choice"] == {"type": "tool", "name": "companion"}
        call = {"type": "tool_use", "id": f"attempt-{len(requests)}",
                "name": "companion" if finish else "desktop_trim",
                "input": {"kind": "quiet"} if finish else {"pid": 123}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        reply = backend.run(runtime.prepare_input(Phase.INITIAL))
        assert reply.boundary == "decision_complete"
        assert len(requests) == 5
        assert all(not row["success"] for row in dialogue.action_results)
        assert dialogue.reports == []
    finally:
        runtime.close()


def test_empty_opening_does_not_finish_a_turn(dialogue):
    reply = dialogue._companion({"kind": "companion", "decision": {"goal": "交流想法"}})
    assert not reply.success and reply.boundary is None
    assert dialogue.decisions == [] and dialogue.reports == []


def test_capture_keeps_only_latest_changed_sample(dialogue, monkeypatch):
    visual = dialogue.task.observation.displayed_observations[0].views[0]
    monkeypatch.setattr(sessionmod, "screen_visual", lambda: visual)
    monkeypatch.setattr(brain.watching, "foreground", lambda: {"proc": "reader", "title": "book"})
    monkeypatch.setattr(brain, "FEEDBACK", sessionmod.CURRENT.parent / "feedback.jsonl")
    screens = brain.LiveScreen()
    first = screens.sample()
    second = screens.sample()
    assert first is second
    monkeypatch.setattr(brain.watching, "foreground", lambda: {"proc": "editor", "title": "project"})
    third = screens.sample()
    assert third.revision == first.revision + 1 and screens.latest() is third


def test_placeholder_does_not_resolve_a_question(monkeypatch):
    rows = [{"role": "user", "text": "理由是什么", "id": "question-1", "t": 100},
            {"role": "assistant", "text": "收到，我记下了", "kind": "reply", "t": 101}]
    monkeypatch.setattr(conversation, "history", lambda limit=80: rows)
    text = brain.conversation_fact(idle_s=0, now=102)
    assert "待回应话轮 id=question-1" in text
    assert "收到，我记下了" not in text
    rows.append({"role": "assistant", "text": "我刚才的依据不充分", "reply_to": "question-1", "t": 103})
    assert conversation.pending_message(rows) is None
    assert "当前没有待回应话轮" in brain.conversation_fact(idle_s=0, now=104)


def test_unrelated_opening_does_not_resolve_a_direct_message():
    rows = [{"role": "user", "id": "question-1", "text": "理由是什么", "t": 100},
            {"role": "assistant", "text": "我看到你打开代码了", "t": 101}]
    assert conversation.pending_message(rows) == rows[0]


def test_reply_identity_survives_publish_and_delivery(dialogue, tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, "LOG", tmp_path / "conversation.jsonl")
    dialogue._companion({"kind": "companion", "say": "这个理由确实不充分。", "intent": "conversation",
                         "reply_to": "question-1"})
    offer = json.loads(helpmod.OFFER.read_text(encoding="utf-8"))
    assert offer["reply_to"] == "question-1"
    row = conversation.append("assistant", offer["text"], event_id=offer["id"], reply_to=offer["reply_to"])
    assert conversation._read(conversation.LOG)[0]["reply_to"] == row["reply_to"]


def test_direct_reply_survives_window_change(dialogue, tmp_path, monkeypatch):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    visual = dialogue.task.observation.displayed_observations[0].views[0]
    initial = brain.ScreenSample(1, visual, [0] * 1440, ("reader", "book"), 100, 99)
    updated = brain.ScreenSample(2, visual, [255] * 1440, ("editor", "project"), 101, 99)

    class Screens:
        current = initial

        def latest(self):
            return self.current

    screens = Screens()
    backend.live_screen = screens
    backend.screen_sample = initial
    backend.screen_revision = 1
    monkeypatch.setattr(conversation, "history", lambda limit=80: [
        {"role": "user", "id": "question-1", "text": "理由是什么", "t": 99}])

    def respond(request, timeout):
        screens.current = updated
        return Response({"content": [{"type": "tool_use", "id": "reply-1", "name": "companion", "input": {
            "kind": "companion", "intent": "conversation", "reply_to": "question-1",
            "say": "刚才的说法太强了，这里更像坦诚自己的状态。"}}], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        result = backend.run(runtime.prepare_input(Phase.INITIAL))
        assert result.boundary == "decision_complete"
        assert len(dialogue.reports) == 1
    finally:
        runtime.close()


def test_quiet_receives_an_explicit_waiting_next_step(dialogue):
    reply = dialogue._companion({"kind": "quiet"})
    assert reply.boundary == "decision_complete"
    assert dialogue.decisions[-1]["next_step"]["status"] == "waiting"
    assert "新画面" in dialogue.decisions[-1]["next_step"]["action"]


def test_current_working_survives_long_guide_and_segment_update(dialogue, tmp_path, monkeypatch):
    experiment = make_experiment(make_profile(), backend="claude", model="test", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(dialogue, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "test", "base_url": "https://model.example", "api_key": "test"}, runtime)
    backend.attach(dialogue)
    runtime.context.guide_path.write_text("old profile " * 400 + "guide-end", encoding="utf-8")
    runtime.context.working_path.write_text("working-before", encoding="utf-8")
    requests = []

    def respond(request, timeout):
        body = json.loads(request.data)
        requests.append(body)
        if len(requests) == 1:
            runtime.context.working_path.write_text("working-after: actual new evidence", encoding="utf-8")
            call = {"type": "tool_use", "id": "read-once", "name": "basic_time", "input": {}}
        else:
            call = {"type": "tool_use", "id": "save-plan", "name": "companion", "input": {"kind": "quiet"}}
        return Response({"content": [call], "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        result = backend.run(runtime.prepare_input(Phase.INITIAL))
        assert result.boundary == "decision_complete"
        first_notes = requests[0]["messages"][0]["content"][0]["text"]
        second_notes = requests[1]["messages"][0]["content"][0]["text"]
        assert "working-before" in first_notes
        assert "guide-end" in first_notes
        assert "working-after: actual new evidence" in second_notes
        assert "working-before" not in second_notes
        assert first_notes.index("[WORKING.md]") < first_notes.index("[GUIDE.md]")
    finally:
        runtime.close()


# --- 不重复自己说过的话 ---------------------------------------------------
#
# 用户反馈："可能会一直说重复的事情"。病因不是模型笨，是它每轮都看不见自己
# 上一轮说了什么——对话现场只附最近一轮，模型于是每轮都重新发现同一件事，
# 把同一条结论换个说法再讲一遍。

def test_sprite_sees_what_it_already_said(monkeypatch):
    rows = [{"role": "assistant", "text": "实验7 报告可以对任务书交了", "kind": "say", "t": 100},
            {"role": "user", "text": "嗯", "id": "ack", "t": 101}]
    monkeypatch.setattr(conversation, "history", lambda limit=80: rows)
    text = brain.conversation_fact(idle_s=0, now=102)
    assert "我最近说过的话" in text
    assert "实验7 报告可以对任务书交了" in text


def test_own_words_survive_a_later_message_from_the_user(monkeypatch):
    """最容易重复的时刻：用户回了个「嗯」之后。历史窗口会滚动，
    但精灵自己说过什么必须一直在场，否则下一句必然是重复。"""
    rows = [{"role": "assistant", "text": "早上那批哈希全对", "kind": "say", "t": 100},
            {"role": "user", "text": "哦", "id": "m2", "t": 101},
            {"role": "user", "text": "接着说", "id": "m3", "t": 102}]
    monkeypatch.setattr(conversation, "history", lambda limit=80: rows)
    text = brain.conversation_fact(idle_s=0, now=103)
    assert "早上那批哈希全对" in text


def test_reply_chatter_is_not_treated_as_something_it_said(monkeypatch):
    """kind=reply 是回话轮的附带产物（常见是「收到，我记下了」这类占位）。
    列进「我最近说过的话」等于主动提醒模型去重复它。"""
    rows = [{"role": "user", "text": "理由是什么", "id": "q", "t": 100},
            {"role": "assistant", "text": "收到，我记下了", "kind": "reply", "t": 101}]
    monkeypatch.setattr(conversation, "history", lambda limit=80: rows)
    text = brain.conversation_fact(idle_s=0, now=102)
    own_block = text.split("【我最近说过的话】")[1].split("【待回应话轮")[0]
    assert "收到，我记下了" not in own_block


def test_first_ever_turn_says_so_instead_of_guessing(monkeypatch):
    rows = [{"role": "user", "text": "在吗", "id": "hi", "t": 100}]
    monkeypatch.setattr(conversation, "history", lambda limit=80: rows)
    text = brain.conversation_fact(idle_s=0, now=102)
    assert "第一次开口" in text
