"""本地代理：把 Codex CLI 的 Responses 接口（流式 SSE）转成 MiMo 的 chat/completions。
支持：文字、图片、函数工具（tools / function_call / function_call_output）的双向转换。
上游 key 只从环境变量 MIMO_API_KEY 读取，不写入任何文件。
python -m sprite.proactive.mimo_proxy [--port 8787]
"""
from __future__ import annotations
import argparse, json, os, time, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
MODEL = "mimo-v2.6-flash"
MAX_TOKENS = 2048


def _content_parts(content) -> list[dict] | str:
    if isinstance(content, str): return content
    parts = []
    for c in content:
        if c.get("type") in ("input_text", "output_text", "text"): parts.append({"type": "text", "text": c.get("text", "")})
        elif c.get("type") == "input_image":
            url = c.get("image_url", "")
            if isinstance(url, dict): url = url.get("url", "")
            parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts or ""


def to_chat_messages(body: dict) -> list[dict]:
    msgs = []
    if body.get("instructions"): msgs.append({"role": "system", "content": body["instructions"]})
    inp = body.get("input", "")
    if isinstance(inp, str): return msgs + [{"role": "user", "content": inp}]
    for item in inp:
        kind = item.get("type", "message")
        if kind == "function_call":
            msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": item["call_id"], "type": "function",
                         "function": {"name": item["name"], "arguments": item.get("arguments", "{}")}}]})
        elif kind == "function_call_output":
            out = item.get("output", "")
            msgs.append({"role": "tool", "tool_call_id": item["call_id"], "content": out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)})
        elif kind == "message":
            role = item.get("role", "user")
            role = role if role in ("system", "assistant") else "user"
            msgs.append({"role": role, "content": _content_parts(item.get("content", ""))})
    return msgs


def to_chat_tools(body: dict) -> list[dict]:
    out = []
    for t in body.get("tools") or []:
        if t.get("type") != "function": continue
        out.append({"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                     "parameters": t.get("parameters", {"type": "object", "properties": {}})}})
    return out


def call_upstream(body: dict) -> dict:
    key = os.environ["MIMO_API_KEY"]
    payload = {"model": MODEL, "messages": to_chat_messages(body), "max_tokens": MAX_TOKENS}
    tools = to_chat_tools(body)
    if tools: payload["tools"] = tools
    req = urllib.request.Request(UPSTREAM, data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r: return json.loads(r.read().decode())


def sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def build_stream(body: dict, data: dict) -> bytes:
    """把 chat 结果变成 Responses 的 SSE 事件序列（文字消息或函数调用）。"""
    choice = data["choices"][0]["message"]
    usage = data.get("usage", {})
    rid = f"resp_{uuid.uuid4().hex}"
    base = {"id": rid, "object": "response", "model": body.get("model", MODEL), "created_at": int(time.time())}
    events, output = [], []
    for call in choice.get("tool_calls") or []:
        item = {"id": f"fc_{uuid.uuid4().hex}", "type": "function_call", "status": "completed", "call_id": call["id"],
                "name": call["function"]["name"], "arguments": call["function"].get("arguments", "{}")}
        idx = len(output); output.append(item)
        events += [sse("response.output_item.added", {"type": "response.output_item.added", "output_index": idx, "item": dict(item, status="in_progress")}),
                   sse("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": item["id"], "output_index": idx, "delta": item["arguments"]}),
                   sse("response.function_call_arguments.done", {"type": "response.function_call_arguments.done", "item_id": item["id"], "output_index": idx, "arguments": item["arguments"]}),
                   sse("response.output_item.done", {"type": "response.output_item.done", "output_index": idx, "item": item})]
    text = choice.get("content") or ""
    if text or not output:
        mid = f"msg_{uuid.uuid4().hex}"
        item = {"id": mid, "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}
        idx = len(output); output.append(item)
        events += [sse("response.output_item.added", {"type": "response.output_item.added", "output_index": idx, "item": dict(item, content=[], status="in_progress")}),
                   sse("response.content_part.added", {"type": "response.content_part.added", "item_id": mid, "output_index": idx, "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}}),
                   sse("response.output_text.delta", {"type": "response.output_text.delta", "item_id": mid, "output_index": idx, "content_index": 0, "delta": text}),
                   sse("response.output_text.done", {"type": "response.output_text.done", "item_id": mid, "output_index": idx, "content_index": 0, "text": text}),
                   sse("response.output_item.done", {"type": "response.output_item.done", "output_index": idx, "item": item})]
    done = dict(base, status="completed", output=output,
                usage={"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0),
                       "total_tokens": usage.get("total_tokens", 0), "input_tokens_details": {"cached_tokens": 0},
                       "output_tokens_details": {"reasoning_tokens": 0}})
    head = [sse("response.created", {"type": "response.created", "response": dict(base, status="in_progress", output=[])})]
    return b"".join(head + events + [sse("response.completed", {"type": "response.completed", "response": done})])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): print("proxy:", fmt % args, flush=True)

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/responses"):
            self.send_error(404); return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            data = call_upstream(body)
        except Exception as e:
            self.send_error(502, f"upstream: {type(e).__name__}: {e}"); return
        out = build_stream(body, data)
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8787); a = ap.parse_args()
    print(f"mimo responses proxy on 127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
