"""MCP 探针：最小的 stdio MCP 服务，只有一个工具 observe，返回最新一张屏幕截图（图片内容块）。
用来验证 opencode 能否把 MCP 工具返回的图片交给模型看。不依赖第三方包。"""
from __future__ import annotations
import base64, glob, json, os, sys

FRAMES = r"E:\OpenLookout\sprite_home\perceive\frames"
TOOLS = [{"name": "observe", "description": "返回用户电脑当前屏幕的最新截图（图片）。",
          "inputSchema": {"type": "object", "properties": {}}}]


def latest_frame() -> str | None:
    fs = glob.glob(os.path.join(FRAMES, "*.jpg"))
    return max(fs, key=os.path.getmtime) if fs else None


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None: return None                                   # 通知（如 initialized）不回复
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "sprite-eyes", "version": "0.1"}}
    if method == "tools/list": return {"tools": TOOLS}
    if method == "tools/call":
        path = latest_frame()
        if not path: return {"content": [{"type": "text", "text": "没有截图"}], "isError": True}
        data = base64.b64encode(open(path, "rb").read()).decode()
        return {"content": [{"type": "image", "data": data, "mimeType": "image/jpeg"},
                            {"type": "text", "text": f"截图时间：{os.path.basename(path)}"}]}
    if method == "ping": return {}
    return {"__error__": f"unknown method {method}"}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        msg = json.loads(line)
        res = handle(msg)
        if res is None: continue
        if "__error__" in res:
            out = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": res["__error__"]}}
        else:
            out = {"jsonrpc": "2.0", "id": msg["id"], "result": res}
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    main()
