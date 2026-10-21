"""Mocked HTTP for the main-model wire. No live endpoint is contacted."""
from __future__ import annotations

import base64
import io
import json

from PIL import Image

from sprite.proactive import chat, help as helpmod
from sprite.proactive.provider import Provider
from vista.benchmarks.desktop import brain


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _png(width: int, height: int) -> dict:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, "PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


def _capture(monkeypatch):
    seen = {}

    def respond(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = {key.lower(): value for key, value in request.header_items()}
        seen["body"] = json.loads(request.data.decode())
        return Response({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    return seen


def test_endpoints_do_not_double_v1():
    assert chat.endpoint("https://host/anthropic", "anthropic") == "https://host/anthropic/v1/messages"
    assert chat.endpoint("http://localhost:11434", "openai") == "http://localhost:11434/v1/chat/completions"
    assert chat.endpoint("http://localhost:11434/v1", "openai") == "http://localhost:11434/v1/chat/completions"
    assert chat.endpoint("https://api.deepseek.com/v1", "openai") == "https://api.deepseek.com/v1/chat/completions"
    assert chat.endpoint("https://api.openai.com/v1", "openai") == "https://api.openai.com/v1/chat/completions"


def test_openai_request_carries_vision_tools_and_no_stream():
    body = {
        "model": "llama",
        "max_tokens": 32,
        "stream": True,
        "system": [{"type": "text", "text": "be brief"}],
        "tool_choice": {"type": "any"},
        "tools": [{"name": "companion", "description": "decide", "input_schema": {"type": "object", "properties": {}}}],
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "look"},
                _png(32, 32),
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": "call-1", "name": "companion", "input": {"kind": "quiet"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": [
                    {"type": "text", "text": "done"},
                    _png(16, 16),
                ]},
            ]},
        ],
    }
    request = chat.build_request(
        {"protocol": "openai", "base_url": "http://localhost:11434/v1", "api_key": "ollama", "model": "llama"},
        body,
    )
    payload = json.loads(request.data.decode())
    headers = {key.lower(): value for key, value in request.header_items()}
    assert request.full_url == "http://localhost:11434/v1/chat/completions"
    assert headers["authorization"] == "Bearer ollama"
    assert "anthropic-version" not in headers
    assert "stream" not in payload
    assert payload["messages"][0] == {"role": "system", "content": "be brief"}
    user = payload["messages"][1]["content"]
    assert any(part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image/png;base64,") for part in user)
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["function"]["name"] == "companion"
    assert payload["tool_choice"] == "required"
    assistant = payload["messages"][2]
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"kind": "quiet"}'
    assert payload["messages"][3]["role"] == "tool"
    assert payload["messages"][4]["content"][0]["text"].startswith("Image returned")


def test_tool_choice_mapping_and_invalid_arguments():
    assert chat._tool_choice({"type": "auto"}) == "auto"
    assert chat._tool_choice({"type": "none"}) == "none"
    assert chat._tool_choice({"type": "tool", "name": "companion"}) == {"type": "function", "function": {"name": "companion"}}
    turned = chat.openai_to_anthropic({
        "choices": [{"finish_reason": "tool_calls", "message": {
            "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": "companion", "arguments": "not-json"}}],
        }}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    })
    assert turned["stop_reason"] == "tool_use"
    assert turned["content"][0]["type"] == "tool_use"
    assert turned["content"][0]["input"] == {}
    assert "JSON" in turned["content"][0]["argument_error"]
    assert "raw" not in turned["content"][0]["input"]
    assert turned["usage"] == {"input_tokens": 3, "output_tokens": 1}
    cached = chat.openai_to_anthropic({
        "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4,
                  "prompt_tokens_details": {"cached_tokens": 5},
                  "cache_creation_input_tokens": 2},
    })
    assert cached["usage"]["input_tokens"] == 9
    assert cached["usage"]["output_tokens"] == 4
    assert cached["usage"]["cache_read_input_tokens"] == 5
    assert cached["usage"]["cache_creation_input_tokens"] == 2
    stopped = chat.openai_to_anthropic({
        "choices": [{"finish_reason": "length", "message": {"content": "partial"}}],
    })
    assert stopped["stop_reason"] == "max_tokens"


def test_anthropic_post_keeps_blocks_and_drops_stream(monkeypatch):
    seen = _capture(monkeypatch)
    payload, request = brain.post_model(
        {"protocol": "anthropic", "base_url": "https://host/anthropic", "api_key": "synthetic", "model": "configured"},
        {"model": "configured", "max_tokens": 8, "stream": True,
         "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]},
    )
    assert request.full_url == "https://host/anthropic/v1/messages"
    assert seen["headers"]["x-api-key"] == "synthetic"
    assert seen["headers"]["anthropic-version"] == chat.ANTHROPIC_VERSION
    assert "authorization" not in seen["headers"]
    assert "stream" not in seen["body"]
    assert payload["content"][0]["text"] == "ok"


def test_post_model_normalizes_openai_tool_call(monkeypatch):
    def respond(request, timeout=None):
        body = json.loads(request.data.decode())
        assert request.full_url == "https://api.openai.com/v1/chat/completions"
        assert body["tool_choice"] == "required"
        assert "stream" not in body
        return Response({
            "choices": [{"finish_reason": "stop", "message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        })

    monkeypatch.setattr("urllib.request.urlopen", respond)
    payload, _request = brain.post_model(
        {"protocol": "openai", "base_url": "https://api.openai.com/v1", "api_key": "synthetic", "model": "gpt"},
        {"model": "gpt", "stream": False, "tool_choice": {"type": "any"},
         "tools": [{"name": "companion", "description": "", "input_schema": {"type": "object"}}],
         "messages": [{"role": "user", "content": "hi"}]},
    )
    assert payload["stop_reason"] == "end_turn"
    assert payload["usage"]["input_tokens"] == 2
    assert payload["content"][0]["text"] == "hello"


def test_help_ask_uses_the_provider_protocol(monkeypatch, tmp_path):
    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), "white").save(frame, "JPEG")
    seen = _capture(monkeypatch)

    def respond(request, timeout=None):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode())
        return Response({"choices": [{"finish_reason": "stop", "message": {"content": '{"kind": "quiet"}'}}]})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    monkeypatch.setattr(helpmod, "load_provider", lambda: Provider(
        "openai", "http://localhost:11434/v1", "your-ollama-model", "ollama"))
    result = helpmod.ask([], frame)
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert any(part.get("type") == "image_url" for part in seen["body"]["messages"][0]["content"])
    assert "stream" not in seen["body"]
    assert result == {"kind": "quiet"}


def test_large_screenshot_is_downscaled_and_small_png_is_kept():
    large = _png(2000, 1000)
    small = _png(40, 30)
    request = chat.build_request(
        {"protocol": "anthropic", "base_url": "https://host/anthropic", "api_key": "synthetic"},
        {"model": "configured", "messages": [{"role": "user", "content": [large, small]}]},
    )
    blocks = json.loads(request.data.decode())["messages"][0]["content"]
    big = Image.open(io.BytesIO(base64.b64decode(blocks[0]["source"]["data"])))
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    assert max(big.size) <= chat.IMAGE_MAX_EDGE
    assert blocks[1]["source"]["media_type"] == "image/png"
    assert blocks[1]["source"]["data"] == small["source"]["data"]


def test_strip_images_keeps_tool_crops():
    messages = [{
        "role": "user",
        "content": [
            _png(20, 20),
            {"type": "tool_result", "tool_use_id": "crop", "content": [_png(12, 12), {"type": "text", "text": "crop"}]},
        ],
    }]
    stripped = chat.strip_images(messages)
    assert stripped[0]["content"][0]["type"] == "text"
    assert "omitted" in stripped[0]["content"][0]["text"]
    nested = stripped[0]["content"][1]["content"]
    assert nested[0]["type"] == "image"
    assert messages[0]["content"][0]["type"] == "image"


def test_consecutive_user_messages_merge_and_tool_roles_stay_split():
    payload = chat.to_openai({
        "model": "m",
        "messages": [
            {"role": "user", "content": "first"},
            {"role": "user", "content": [{"type": "text", "text": "second"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            {"role": "user", "content": "third"},
            {"role": "user", "content": "fourth"},
        ],
    })
    roles = [message["role"] for message in payload["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]
    assert payload["messages"][2]["content"] == "third\nfourth"


def test_model_call_budget_defaults_to_four_and_caps_at_eight(monkeypatch):
    monkeypatch.delenv("OPENLOOKOUT_MAX_CALLS", raising=False)
    assert brain.model_call_budget() == 4
    assert brain.model_call_budget({"OPENLOOKOUT_MAX_CALLS": "0"}) == 1
    assert brain.model_call_budget({"OPENLOOKOUT_MAX_CALLS": "99"}) == 8
    assert brain.model_call_budget({"OPENLOOKOUT_MAX_CALLS": "nope"}) == 4
    monkeypatch.setenv("OPENLOOKOUT_MAX_CALLS", "6")
    backend = brain.VisualDirectBackend({})
    assert backend.max_segments == 5
