"""OpenLookout 真实记录器（Python 原型，Linux/X11）。
记录窗口切换、文件变动、剪贴板，输出与 capture/events.jsonl 相同格式的事件。
只用标准库 + xprop/xclip 命令；不截图，不记键盘。

用法：
  python3 recorder/record.py --watch ~/文档 --watch ~/下载 --out recorder/out/events.jsonl
  --keep-text  才会把剪贴板原文写进事件（默认只写长度和哈希）
"""
import argparse, threading, http.server, ctypes, ctypes.util, hashlib, json, os, select, struct, subprocess, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
def now_ts(): return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")

def sh(*cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
    except Exception: return ""

# ---------- 窗口 ----------
def active_window():
    """返回 (app, title)；app 取 WM_CLASS 的类名，统一小写。"""
    out = sh("xprop", "-root", "_NET_ACTIVE_WINDOW")
    wid = out.split("#", 1)[1].split(",")[0].strip() if "#" in out else ""
    if not wid or wid in ("0x0",): return None
    info = sh("xprop", "-id", wid, "WM_CLASS", "_NET_WM_NAME")
    app = title = ""
    for line in info.splitlines():
        if "=" not in line: continue
        if line.startswith("WM_CLASS"):
            parts = [p.strip().strip('"') for p in line.split("=", 1)[1].split(",")]
            app = (parts[-1] or parts[0]).lower()
        elif line.startswith("_NET_WM_NAME"):
            title = line.split("=", 1)[1].strip().strip('"')
    return (app, title) if app or title else None

# ---------- 剪贴板 ----------
def clipboard_text():
    return sh("xclip", "-o", "-selection", "clipboard")

# ---------- 文件（inotify，ctypes） ----------
IN_OPEN, IN_CLOSE_WRITE, IN_MOVED_TO, IN_CREATE, IN_ISDIR = 0x20, 0x08, 0x80, 0x100, 0x40000000
MASK = IN_OPEN | IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE
IGNORE_SUFFIX = (".swp", ".tmp", "~", ".part", ".crdownload", ".lock")
class Inotify:
    def __init__(self):
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        self.libc = libc; self.fd = libc.inotify_init1(os.O_NONBLOCK); self.wd = {}
    def add_tree(self, root):
        for d, dirs, _ in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            w = self.libc.inotify_add_watch(self.fd, d.encode(), MASK)
            if w >= 0: self.wd[w] = Path(d)
    def read(self):
        try: buf = os.read(self.fd, 65536)
        except BlockingIOError: return []
        out, i = [], 0
        while i < len(buf):
            wd, mask, _, ln = struct.unpack_from("iIII", buf, i); i += 16
            name = buf[i:i+ln].rstrip(b"\0").decode(errors="replace"); i += ln
            if wd in self.wd: out.append((self.wd[wd] / name, mask))
        return out

# ---------- 浏览器扩展接收端 ----------
BROWSER_APPS = ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "msedge", "brave-browser", "firefox", "navigator")
class ExtState:
    def __init__(self): self.lock = threading.Lock(); self.url_by_title = {}; self.last_url = None; self.queue = []
def start_ext_server(port, st):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_OPTIONS(self):
            self.send_response(204); self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.end_headers()
        def do_POST(self):
            try: ev = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except Exception: ev = {}
            with st.lock:
                if ev.get("kind") == "url" and ev.get("url"):
                    st.url_by_title[ev.get("title", "")] = ev["url"]; st.last_url = ev["url"]
                elif ev.get("kind") == "form_edit":
                    st.queue.append(dict(ts=now_ts(), url=ev.get("url"), field_label=ev.get("field_label"), via=ev.get("via")))
            self.send_response(204); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

def url_for(st, app, title):
    if app not in BROWSER_APPS: return None
    with st.lock:
        for t, u in st.url_by_title.items():
            if t and title and title.startswith(t): return u
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="append", default=[])
    ap.add_argument("--out", default=str(Path(__file__).parent / "out" / "events.jsonl"))
    ap.add_argument("--home", default=str(Path.home()), help="事件里的路径相对于它的上一级（与模拟数据一致）")
    ap.add_argument("--keep-text", action="store_true")
    ap.add_argument("--poll", type=float, default=0.5)
    ap.add_argument("--ext-port", type=int, default=8765, help="浏览器扩展上报端口，0 表示关闭")
    ap.add_argument("--seconds", type=float, default=0, help="跑多久后退出，0 表示一直跑")
    a = ap.parse_args()
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    f = open(out, "a", encoding="utf-8")
    base = Path(a.home).resolve().parent
    def emit(type_, ts=None, **kw):
        e = {"ts": ts or now_ts(), "type": type_}; e.update({k: v for k, v in kw.items() if v is not None})
        f.write(json.dumps(e, ensure_ascii=False) + "\n"); f.flush()
    def rel(p):
        try: return str(Path(p).resolve().relative_to(base))
        except ValueError: return str(p)

    st = ExtState()
    if a.ext_port: start_ext_server(a.ext_port, st)
    ino = Inotify()
    for w in a.watch: ino.add_tree(os.path.expanduser(w))
    cur, cur_ts, cur_t = None, None, None      # 当前焦点窗口
    last_clip = clipboard_text(); pending_clip = None
    recent_open = {}                           # 去重：同一文件 5 秒内只记一次 open/save
    t0 = time.time()
    while not a.seconds or time.time() - t0 < a.seconds:
        # 焦点
        try: w = active_window()
        except Exception: w = cur
        if w != cur:
            if cur and cur_t and (cur[1] or time.time() - cur_t >= 1):
                emit("focus", cur_ts, app=cur[0], title=cur[1], url=url_for(st, cur[0], cur[1]), dur_s=int(time.time() - cur_t))
            if pending_clip and w:             # 复制后切到的第一个其他窗口，记为粘贴目标
                pending_clip.update(dst_app=w[0], dst_title=w[1]); emit("clipboard", **pending_clip); pending_clip = None
            cur, cur_ts, cur_t = w, now_ts(), time.time()
        # 浏览器表单
        with st.lock: q, st.queue = st.queue, []
        for fe in q:
            if fe.get("via") == "paste" and pending_clip and cur:   # 在同一窗口里粘贴，粘贴目标就是当前窗口
                pending_clip.update(dst_app=cur[0], dst_title=cur[1]); emit("clipboard", **pending_clip); pending_clip = None
            emit("form_edit", fe.pop("ts"), app=cur[0] if cur else None, **fe)
        # 剪贴板
        c = clipboard_text()
        if c and c != last_clip:
            last_clip = c
            if pending_clip: emit("clipboard", **pending_clip)
            pending_clip = dict(ts=now_ts(), src_app=cur[0] if cur else None, src_title=cur[1] if cur else None,
                                len=len(c), hash=hashlib.sha256(c.encode()).hexdigest()[:12],
                                text=c if a.keep_text else None)
        # 文件
        for p, mask in ino.read():
            if mask & IN_ISDIR:
                if mask & IN_CREATE: ino.add_tree(p)
                continue
            if p.name.startswith((".", "~$", ".~lock")) or p.name.endswith(IGNORE_SUFFIX): continue
            kind = "file_save" if mask & (IN_CLOSE_WRITE | IN_MOVED_TO) else "file_open" if mask & IN_OPEN else None
            if not kind: continue
            key = (kind, str(p)); tnow = time.time()
            if tnow - recent_open.get(key, 0) < 5: continue
            recent_open[key] = tnow
            emit(kind, path=rel(p), app=cur[0] if cur else None)
        r, _, _ = select.select([ino.fd], [], [], a.poll)
    if cur and cur_t: emit("focus", cur_ts, app=cur[0], title=cur[1], url=url_for(st, cur[0], cur[1]), dur_s=int(time.time() - cur_t))
    if pending_clip: emit("clipboard", **pending_clip)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
