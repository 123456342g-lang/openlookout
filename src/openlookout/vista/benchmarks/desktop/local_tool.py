"""Local, non-MCP bridge from Claude Code's host Bash to VISTA tools.

The bridge is deliberately loopback-only and authenticated with a per-session
token.  Claude Code invokes the small CLI in this module; the CLI forwards the
request to the brain process, where the existing TaskRuntime performs schema,
budget, acknowledgement, and action-boundary checks.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen


class _Handler(BaseHTTPRequestHandler):
    server_version = "OpenLookoutLocalTool/1"

    def log_message(self, *_args):
        return

    def do_POST(self):  # noqa: N802
        owner = self.server.owner
        if self.path != "/invoke":
            self.send_error(404)
            return
        if self.headers.get("X-OpenLookout-Token") != owner.token:
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            tool = str(payload["tool"])
            arguments = payload.get("arguments", {})
            owner.counter += 1
            execution = owner.runtime.execute(tool, arguments, f"local-cli-{owner.counter}")
            owner.runtime.acknowledge()
            result = {
                "success": bool(execution.success),
                "text": str(execution.text),
                "boundary": execution.boundary_reason,
                "interrupt_after": bool(execution.interrupt_after),
            }
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # keep the model loop alive on malformed calls
            body = json.dumps({"success": False, "text": f"local tool error: {type(exc).__name__}: {exc}"}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class LocalToolServer:
    def __init__(self, runtime):
        self.runtime = runtime
        self.token = secrets.token_urlsafe(24)
        self.counter = 0
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.owner = self
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_port}/invoke"
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="vista-local-tools")
            self.thread.start()

    def close(self):
        self.httpd.shutdown()


def invoke_cli(tool: str, arguments: str) -> int:
    endpoint = os.environ.get("OPENLOOKOUT_LOCAL_TOOL_ENDPOINT")
    token = os.environ.get("OPENLOOKOUT_LOCAL_TOOL_TOKEN")
    if not endpoint or not token:
        print("local VISTA tool bridge is unavailable", file=sys.stderr)
        return 2
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"success": False, "text": f"invalid JSON arguments: {exc}"}, ensure_ascii=False))
        return 2
    request = Request(endpoint, data=json.dumps({"tool": tool, "arguments": payload}, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "X-OpenLookout-Token": token}, method="POST")
    try:
        with urlopen(request, timeout=120) as response:
            print(response.read().decode("utf-8", errors="replace"))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "text": f"local VISTA tool request failed: {type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tool")
    parser.add_argument("arguments", nargs="?", default="{}")
    args = parser.parse_args()
    return invoke_cli(args.tool, args.arguments)


if __name__ == "__main__":
    raise SystemExit(main())
