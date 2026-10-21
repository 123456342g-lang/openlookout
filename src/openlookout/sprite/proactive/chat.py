"""Wire format for the main model.

The resident brain and help.ask keep Anthropic-shaped content blocks in
memory. This module converts them only at the HTTP boundary.

* protocol ``anthropic`` posts ``{base}/v1/messages``
* protocol ``openai`` posts ``{base}/v1/chat/completions``

A base URL that already ends in ``/v1`` is not doubled, so both
``http://localhost:11434`` and ``http://localhost:11434/v1`` work.

The client waits for one JSON body. ``stream`` is never sent. An endpoint
that only speaks server-sent events will fail. Whether a local model honors
vision or tools depends on that model.
"""
from __future__ import annotations

import base64
import io
import json
import urllib.request

from PIL import Image

IMAGE_MAX_EDGE = 768
IMAGE_JPEG_QUALITY = 55
ANTHROPIC_VERSION = "2023-06-01"


def endpoint(base_url: str, protocol: str) -> str:
    base = str(base_url or "").rstrip("/")
    if protocol == "openai":
        tail = "/chat/completions"
    elif protocol == "anthropic":
        tail = "/messages"
    else:
        raise ValueError(f"protocol must be anthropic or openai, got {protocol!r}")
    if base.endswith("/v1"):
        return base + tail
    return base + "/v1" + tail


def headers(api_key: str, protocol: str) -> dict[str, str]:
    common = {"Content-Type": "application/json"}
    if protocol == "openai":
        return {"Authorization": "Bearer " + api_key, **common}
    if protocol != "anthropic":
        raise ValueError(f"protocol must be anthropic or openai, got {protocol!r}")
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        **common,
    }


def shrink_image_block(block: dict) -> dict:
    """Downscale a base64 image before it is put on the wire.

    Pictures already within IMAGE_MAX_EDGE stay as they are, including PNG
    crops from inspect and evidence tools. Only an oversized frame is resized
    and stored as JPEG.
    """
    source = block.get("source") if isinstance(block, dict) else None
    if not isinstance(source, dict) or source.get("type") != "base64":
        return block
    raw_b64 = source.get("data") or ""
    try:
        raw = base64.b64decode(raw_b64)
        image = Image.open(io.BytesIO(raw))
        edge = max(image.size)
        if edge <= IMAGE_MAX_EDGE:
            return block
        image = image.convert("RGB")
        scale = IMAGE_MAX_EDGE / float(edge)
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
        data = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return block
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def shrink_blocks(blocks: list) -> list:
    shrunk = []
    for block in blocks:
        if not isinstance(block, dict):
            shrunk.append(block)
            continue
        if block.get("type") == "image":
            shrunk.append(shrink_image_block(block))
        elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
            shrunk.append(dict(block, content=shrink_blocks(block["content"])))
        else:
            shrunk.append(block)
    return shrunk


def shrink_messages(messages: list) -> list:
    out = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            out.append(dict(message, content=shrink_blocks(content)))
        else:
            out.append(message)
    return out


def strip_images(messages: list) -> list:
    """Drop top-level screenshots when the screen did not change.

    Images nested in tool results stay. Those are crops the model just asked
    to see, and they are not another copy of the full screen.
    """
    note = {"type": "text", "text": "Screen unchanged since the last image in this turn; image omitted."}
    out = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            out.append(message)
            continue
        kept = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image":
                kept.append(note)
            else:
                kept.append(block)
        out.append(dict(message, content=kept))
    return out


def _image_part(block: dict) -> dict | None:
    source = block.get("source") or {}
    if source.get("type") != "base64" or not source.get("data"):
        return None
    mime = source.get("media_type") or "image/jpeg"
    url = f"data:{mime};base64,{source['data']}"
    return {"type": "image_url", "image_url": {"url": url}}


def _text_of(block: dict) -> str:
    if block.get("type") == "text":
        return str(block.get("text") or "")
    return ""


def _tool_result_text(block: dict) -> tuple[str, list[dict]]:
    content = block.get("content")
    texts: list[str] = []
    images: list[dict] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                texts.append(str(item.get("text") or ""))
            elif item.get("type") == "image":
                part = _image_part(item)
                if part is not None:
                    images.append(part)
    text = "\n".join(part for part in texts if part).strip()
    if block.get("is_error"):
        text = ("Error: " + text) if text else "Error"
    return text or "(no text)", images


def _user_parts(blocks: list) -> list[dict]:
    parts = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and _text_of(block):
            parts.append({"type": "text", "text": _text_of(block)})
        elif block.get("type") == "image":
            part = _image_part(block)
            if part is not None:
                parts.append(part)
    return parts


def _assistant_message(content) -> dict:
    if isinstance(content, str):
        return {"role": "assistant", "content": content}
    texts: list[str] = []
    calls = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            arguments = block.get("input", {})
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            calls.append({
                "id": str(block.get("id") or f"call_{len(calls) + 1}"),
                "type": "function",
                "function": {"name": str(block.get("name") or ""), "arguments": arguments},
            })
    message: dict = {"role": "assistant", "content": "".join(texts)}
    if calls:
        message["tool_calls"] = calls
    return message


def _convert_messages(messages: list) -> list[dict]:
    converted = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role == "assistant":
            converted.append(_assistant_message(content))
            continue
        if isinstance(content, str):
            converted.append({"role": role or "user", "content": content})
            continue
        blocks = content if isinstance(content, list) else []
        tool_blocks = [block for block in blocks if isinstance(block, dict) and block.get("type") == "tool_result"]
        others = [block for block in blocks if not (isinstance(block, dict) and block.get("type") == "tool_result")]
        images: list[dict] = []
        for block in tool_blocks:
            text, pictures = _tool_result_text(block)
            converted.append({
                "role": "tool",
                "tool_call_id": str(block.get("tool_use_id") or ""),
                "content": text,
            })
            if pictures:
                note = "Image returned with tool_use_id=" + str(block.get("tool_use_id") or "")
                images.append({"type": "text", "text": note})
                images.extend(pictures)
        parts = _user_parts(others) + images
        if parts:
            converted.append({"role": "user", "content": parts})
        elif not tool_blocks:
            converted.append({"role": "user", "content": ""})
    return converted


def _tool_spec(tool: dict) -> dict:
    schema = tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool.get("name") or "",
            "description": tool.get("description") or "",
            "parameters": schema,
        },
    }


def _tool_choice(choice):
    if choice is None:
        return None
    if isinstance(choice, str):
        return choice
    if not isinstance(choice, dict):
        return None
    kind = choice.get("type")
    if kind == "any":
        return "required"
    if kind in {"auto", "none"}:
        return kind
    if kind == "tool":
        return {"type": "function", "function": {"name": choice.get("name")}}
    return None


def _system_text(system) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "".join(_text_of(block) for block in system if isinstance(block, dict))
    return ""


def to_openai(body: dict) -> dict:
    messages = []
    system = _system_text(body.get("system"))
    if system.strip():
        messages.append({"role": "system", "content": system})
    messages.extend(_convert_messages(body.get("messages") or []))
    payload: dict = {"model": body.get("model"), "messages": messages}
    if body.get("max_tokens") is not None:
        payload["max_tokens"] = body["max_tokens"]
    tools = body.get("tools") or []
    if tools:
        payload["tools"] = [_tool_spec(tool) for tool in tools]
        choice = _tool_choice(body.get("tool_choice"))
        if choice is not None:
            payload["tool_choice"] = choice
    return payload


def _parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(value, dict):
        return value
    return {"raw": raw}


def _openai_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return str(content)


def _stop_reason(finish, has_tools: bool) -> str:
    if finish == "tool_calls" or (has_tools and finish in {None, ""}):
        return "tool_use"
    if finish == "stop" or finish in {None, ""}:
        return "end_turn"
    if finish == "length":
        return "max_tokens"
    return str(finish)


def openai_to_anthropic(payload: dict) -> dict:
    choices = payload.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    finish = choices[0].get("finish_reason") if choices else None
    blocks = []
    text = _openai_text(message.get("content")).strip()
    if text:
        blocks.append({"type": "text", "text": text})
    calls = message.get("tool_calls") or []
    for index, call in enumerate(calls):
        function = call.get("function") or {}
        blocks.append({
            "type": "tool_use",
            "id": str(call.get("id") or f"call_{index + 1}"),
            "name": function.get("name") or "",
            "input": _parse_arguments(function.get("arguments")),
        })
    usage = payload.get("usage") or {}
    return {
        "content": blocks,
        "stop_reason": _stop_reason(finish, bool(calls)),
        "usage": {
            "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
            "output_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
        },
    }


def normalize_response(protocol: str, payload: dict) -> dict:
    if protocol == "openai":
        return openai_to_anthropic(payload if isinstance(payload, dict) else {})
    return payload if isinstance(payload, dict) else {}


def build_request(cfg: dict, body: dict) -> urllib.request.Request:
    protocol = str(cfg.get("protocol") or "anthropic")
    prepared = {key: value for key, value in body.items() if key != "stream"}
    if isinstance(prepared.get("messages"), list):
        prepared["messages"] = shrink_messages(prepared["messages"])
    if protocol == "openai":
        payload = to_openai(prepared)
    elif protocol == "anthropic":
        payload = prepared
    else:
        raise ValueError(f"protocol must be anthropic or openai, got {protocol!r}")
    payload.pop("stream", None)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(
        endpoint(str(cfg.get("base_url") or ""), protocol),
        data=data,
        headers=headers(str(cfg.get("api_key") or ""), protocol),
        method="POST",
    )


def complete(cfg: dict, body: dict, *, timeout: float, opener=None) -> dict:
    protocol = str(cfg.get("protocol") or "anthropic")
    request = build_request(cfg, body)
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode())
    return normalize_response(protocol, payload)
