"""OpenLookout 真实记录器（Python 原型，Windows 10/11）。
输出格式与 capture/events.jsonl、recorder/record.py 相同。只用 Python 标准库（ctypes 调 Win32），
不截图，不记键盘。

用法（PowerShell）：
  python record_win.py --watch "$HOME\\Documents" --watch "$HOME\\Downloads" --seconds 600
  --keep-text  才把剪贴板原文写进事件（默认只写长度和哈希）
"""
import argparse, ctypes, hashlib, http.server, json, os, sys, threading, time
from ctypes import wintypes as W
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform != "win32":
    sys.exit("这个脚本只能在 Windows 上运行；Linux 请用 recorder/record.py")

TZ = timezone(timedelta(hours=8))
def now_ts(): return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetForegroundWindow.restype = W.HWND
user32.GetWindowTextLengthW.argtypes = [W.HWND]
user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user32.GetClipboardSequenceNumber.restype = W.DWORD
user32.OpenClipboard.argtypes = [W.HWND]
user32.GetClipboardData.restype = W.HANDLE
user32.GetClipboardData.argtypes = [W.UINT]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
kernel32.CloseHandle.argtypes = [W.HANDLE]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [W.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [W.HGLOBAL]

# 进程名 -> 与 Linux 版一致的 app 名，方便分析侧同一套规则
APP_ALIAS = {
    "chrome": "google-chrome", "msedge": "microsoft-edge", "firefox": "firefox", "brave": "brave-browser", "tabbit browser": "tabbit", "tabbit": "tabbit",
    "excel": "excel", "winword": "word", "powerpnt": "powerpoint", "wps": "wps", "et": "wps-et", "wpp": "wps-wpp",
    "code": "code", "explorer": "explorer", "wechat": "wechat", "weixin": "wechat", "qq": "qq",
    "dingtalk": "dingtalk", "feishu": "feishu", "lark": "feishu", "notepad": "notepad",
}
def soffice_app(title):
    t = title.lower()
    for k, v in (("calc", "libreoffice-calc"), ("writer", "libreoffice-writer"), ("impress", "libreoffice-impress")):
        if k in t: return v
    return "libreoffice"

# ---------- 窗口 ----------
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
def exe_name(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h: return ""
    try:
        buf = ctypes.create_unicode_buffer(1024); n = W.DWORD(1024)
        return Path(buf.value).stem.lower() if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally: kernel32.CloseHandle(h)

def active_window():
    hwnd = user32.GetForegroundWindow()
    if not hwnd: return None
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1); user32.GetWindowTextW(hwnd, buf, n + 1)
    title = buf.value
    pid = W.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = exe_name(pid.value)
    app = soffice_app(title) if exe == "soffice" or exe == "soffice.bin" else APP_ALIAS.get(exe, exe)
    return (app, title) if app or title else None

# ---------- 剪贴板 ----------
CF_UNICODETEXT = 13
def clipboard_text():
    for _ in range(5):                       # 别的程序可能正占着剪贴板
        if user32.OpenClipboard(None): break
        time.sleep(0.05)
    else: return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h: return ""
        p = kernel32.GlobalLock(h)
        if not p: return ""
        try: return ctypes.wstring_at(p)
        finally: kernel32.GlobalUnlock(h)
    finally: user32.CloseClipboard()

# ---------- 文件 ----------
# 保存：ReadDirectoryChangesW 监听 --watch 目录。
# 打开：Windows 不提供“谁打开了文件”的通知；资源管理器和 Office 打开文件时会在
#       %APPDATA%\Microsoft\Windows\Recent 里新建/更新一个 <文件名>.lnk，借它推断 file_open。
FILE_LIST_DIRECTORY, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS = 0x1, 3, 0x02000000
SHARE_ALL = 0x1 | 0x2 | 0x4
NOTIFY = 0x1 | 0x10 | 0x8                    # 文件名、最后写入时间、大小
ACTION_ADDED, ACTION_MODIFIED, ACTION_RENAMED_NEW = 1, 3, 5
kernel32.CreateFileW.restype = W.HANDLE
kernel32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
kernel32.ReadDirectoryChangesW.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD, W.BOOL, W.DWORD,
                                           ctypes.POINTER(W.DWORD), ctypes.c_void_p, ctypes.c_void_p]
IGNORE_SUFFIX = (".tmp", "~", ".part", ".crdownload", ".lock", ".lnk", ".ini")

def watch_dir(root, cb):
    h = kernel32.CreateFileW(str(root), FILE_LIST_DIRECTORY, SHARE_ALL, None, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None)
    if h in (None, ctypes.c_void_p(-1).value):
        print(f"无法监听 {root}", file=sys.stderr); return
    buf = ctypes.create_string_buffer(64 * 1024); got = W.DWORD()
    while kernel32.ReadDirectoryChangesW(h, buf, len(buf), True, NOTIFY, ctypes.byref(got), None, None):
        i = 0
        while got.value:
            nxt, action, ln = (int.from_bytes(buf.raw[i+k:i+k+4], "little") for k in (0, 4, 8))
            name = buf.raw[i+12:i+12+ln].decode("utf-16-le")
            cb(Path(root) / name, action)
            if not nxt: break
            i += nxt

# ---------- 浏览器扩展接收端（与 Linux 版同一协议，recorder/extension 可直接装） ----------
BROWSER_APPS = ("google-chrome", "microsoft-edge", "brave-browser", "firefox", "tabbit")
class Shared:
    def __init__(self): self.lock = threading.Lock(); self.url_by_title = {}; self.last_url = None; self.queue = []; self.files = []
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
        return st.last_url

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
    if not a.watch: a.watch = [str(Path.home() / "Documents"), str(Path.home() / "Desktop"), str(Path.home() / "Downloads")]
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    f = open(out, "a", encoding="utf-8"); flock = threading.Lock()
    base = Path(a.home).resolve().parent
    def emit(type_, ts=None, **kw):
        e = {"ts": ts or now_ts(), "type": type_}; e.update({k: v for k, v in kw.items() if v is not None})
        with flock: f.write(json.dumps(e, ensure_ascii=False) + "\n"); f.flush()
    def rel(p):
        try: return Path(p).resolve().relative_to(base).as_posix()
        except ValueError: return Path(p).as_posix()

    st = Shared()
    if a.ext_port: start_ext_server(a.ext_port, st)
    roots = [Path(os.path.expanduser(w)) for w in a.watch if Path(os.path.expanduser(w)).is_dir()]
    def on_change(p, action):
        if action in (ACTION_ADDED, ACTION_MODIFIED, ACTION_RENAMED_NEW) and not p.is_dir():
            with st.lock: st.files.append(("file_save", p, now_ts()))
    for r in roots: threading.Thread(target=watch_dir, args=(r, on_change), daemon=True).start()
    recent = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"
    def on_recent(p, action):
        if p.suffix.lower() == ".lnk" and action in (ACTION_ADDED, ACTION_MODIFIED, ACTION_RENAMED_NEW):
            name = p.stem                    # “报告.docx.lnk” -> “报告.docx”
            if "." not in name: return       # 文件夹的快捷方式不记
            hit = next((q for r in roots for q in r.rglob(name)), None)
            with st.lock: st.files.append(("file_open", hit or Path(name), now_ts()))
    if recent.is_dir(): threading.Thread(target=watch_dir, args=(recent, on_recent), daemon=True).start()

    print(f"正在记录到 {out}，监听 {', '.join(map(str, roots)) or '（无目录）'}；按 Ctrl+C 结束。", file=sys.stderr)
    cur, cur_ts, cur_t = None, None, None
    last_seq = user32.GetClipboardSequenceNumber(); last_clip = clipboard_text(); pending_clip = None
    recent_seen = {}
    t0 = time.time()
    while not a.seconds or time.time() - t0 < a.seconds:
        try: w = active_window()
        except Exception: w = cur
        if w != cur:
            if cur and cur_t and (cur[1] or time.time() - cur_t >= 1):
                emit("focus", cur_ts, app=cur[0], title=cur[1], url=url_for(st, cur[0], cur[1]), dur_s=int(time.time() - cur_t))
            if pending_clip and w:           # 复制后切到的第一个其他窗口，记为粘贴目标
                pending_clip.update(dst_app=w[0], dst_title=w[1]); emit("clipboard", **pending_clip); pending_clip = None
            cur, cur_ts, cur_t = w, now_ts(), time.time()
        with st.lock: q, st.queue = st.queue, []; fs, st.files = st.files, []
        for fe in q: emit("form_edit", fe.pop("ts"), app=cur[0] if cur else None, **fe)
        seq = user32.GetClipboardSequenceNumber()
        if seq != last_seq:
            last_seq = seq; c = clipboard_text()
            if c and c != last_clip:
                last_clip = c
                if pending_clip: emit("clipboard", **pending_clip)
                pending_clip = dict(ts=now_ts(), src_app=cur[0] if cur else None, src_title=cur[1] if cur else None,
                                    len=len(c), hash=hashlib.sha256(c.encode("utf-8")).hexdigest()[:12],
                                    text=c if a.keep_text else None)
        for kind, p, ts in fs:
            if p.name.startswith((".", "~$", "~WRL")) or p.name.lower().endswith(IGNORE_SUFFIX): continue
            key = (kind, str(p)); tnow = time.time()
            if tnow - recent_seen.get(key, 0) < 5: continue
            recent_seen[key] = tnow
            emit(kind, ts, path=rel(p), app=cur[0] if cur else None)
        time.sleep(a.poll)
    if cur and cur_t: emit("focus", cur_ts, app=cur[0], title=cur[1], url=url_for(st, cur[0], cur[1]), dur_s=int(time.time() - cur_t))
    if pending_clip: emit("clipboard", **pending_clip)
    print(f"已结束，事件在 {out}", file=sys.stderr)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("已结束", file=sys.stderr)
