"""OpenLookout 历史回溯导入（Windows，一次性运行）。

把电脑上【已经存在】的使用痕迹转成 events.jsonl（格式同 recorder/、recorder_win/），
让发现流水线第一天就能在过去几个月的历史上跑，而不用长期实时监控。

只读：不修改、不删除、不移动用户电脑上的任何文件；不联网、不上传；只往 --out 目录写。
只用 Python 3.11 标准库（sqlite3、struct、winreg），不需要 pip 安装任何东西。

读什么（每一项都可选，找不到就跳过并在日志里记一笔）：
  1. 浏览器历史：Chrome / Edge / Brave / Tabbit 等 Chromium 内核浏览器的 History（访问记录 + 下载记录），
     Firefox 的 places.sqlite。先把数据库复制到 --out\\_tmp 再读，读完就删副本。
     绝不读取 Cookies、Login Data（密码）、Web Data（自动填充）、书签以外的任何东西。
  2. 系统“最近使用”：%APPDATA%\\Microsoft\\Windows\\Recent\\*.lnk（解析快捷方式里的目标路径）；
     Office 的“最近使用文件”列表（注册表 File MRU，只读）。
  3. 文件夹元数据：文档、桌面、下载 + --roots 指定的文件夹里，文档/表格/PDF 等文件的
     创建时间、修改时间、大小、路径。默认不打开文件内容。

可选 --with-content：把近期的表格/文本类文件【复制】一份到 --out\\content\\，给后面的“解决”步骤用。
默认关闭。

用法（PowerShell）：
  D:\\python3.11\\python.exe backfill_win.py --plan                     # 只列出会读哪些来源，什么都不读
  D:\\python3.11\\python.exe backfill_win.py --days 90 --roots E:\\ --roots D:\\项目
"""
import argparse, json, ntpath, os, posixpath, re, shutil, sqlite3, struct, sys, time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote

IS_WIN = os.name == "nt"
VERSION = "0.1"

DOC_EXT = {".xlsx", ".xls", ".xlsm", ".csv", ".docx", ".doc", ".pdf", ".pptx", ".ppt", ".txt", ".md",
           ".et", ".wps", ".dps", ".ett", ".wpt"}
CONTENT_EXT = {".xlsx", ".xlsm", ".csv", ".txt", ".md", ".docx"}  # --with-content 只复制这些
SKIP_DIRS = {"node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "env", "site-packages",
             "windows", "program files", "program files (x86)", "programdata", "appdata", "$recycle.bin",
             "system volume information", "recovery", "perflogs", "msocache", "$windows.~bt", "$windows.~ws",
             "anaconda3", "miniconda3", ".conda", ".cache", ".npm", ".gradle", ".m2", ".cargo", ".rustup",
             ".idea", ".vscode", "build", "dist", "target", "steamapps", "steamlibrary", "windowsapps",
             "wechat files", "tencent files", "xwechat_files", "openlookout"}   # 微信/QQ 聊天文件夹默认不扫
# 这些浏览器文件永远不碰（密码、Cookie、自动填充、扩展存储）
NEVER_TOUCH = {"login data", "login data for account", "cookies", "web data", "network", "local storage",
               "extension cookies", "key4.db", "logins.json", "cookies.sqlite", "formhistory.sqlite"}
SENSITIVE_PARAM = re.compile(r"^(access_?token|token|code|session(id)?|sid|jsessionid|key|api_?key|password|passwd|pwd|"
                             r"secret|sig|signature|auth|authorization|ticket|st|otp|state|nonce)$", re.I)
SKIP_URL = ("chrome://", "edge://", "brave://", "about:", "chrome-extension://", "extension://", "devtools://",
            "view-source:", "data:", "blob:", "javascript:", "chrome-search://", "chrome-untrusted://", "moz-extension://")
# 浏览器名 -> app 名（与 recorder_win 的 APP_ALIAS 一致）
BROWSER_APP = {"chrome": "google-chrome", "edge": "microsoft-edge", "brave": "brave-browser", "tabbit": "tabbit",
               "firefox": "firefox", "chromium": "chromium", "vivaldi": "vivaldi", "opera": "opera", "360": "360se",
               "qq": "qqbrowser", "sogou": "sogou-explorer"}
EXT_APP = {".xlsx": "excel", ".xls": "excel", ".xlsm": "excel", ".csv": "excel", ".docx": "word", ".doc": "word",
           ".pptx": "powerpoint", ".ppt": "powerpoint", ".pdf": "pdf-viewer", ".txt": "notepad", ".md": "notepad",
           ".et": "wps-et", ".ett": "wps-et", ".wps": "wps", ".wpt": "wps", ".dps": "wps-wpp"}
CHROME_CORE = {0: "link", 1: "typed", 2: "bookmark", 3: "subframe", 4: "subframe", 5: "generated", 6: "toplevel",
               7: "form_submit", 8: "reload", 9: "keyword", 10: "keyword"}
FF_TYPE = {1: "link", 2: "typed", 3: "bookmark", 4: "embed", 5: "redirect", 6: "redirect", 7: "download", 8: "embed", 9: "reload"}

UTC = timezone.utc
WEBKIT_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)

# ------------------------------------------------------------------ 时间
class Clock:
    def __init__(self, tz_arg, now_arg, days):
        if tz_arg:
            m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", tz_arg)
            if not m: sys.exit("--tz 格式应为 +08:00")
            sign = 1 if m.group(1) == "+" else -1
            self.tz = timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
        else:
            self.tz = None   # 用系统时区
        self.now = datetime.fromisoformat(now_arg).astimezone(self.tz) if now_arg else datetime.now(UTC).astimezone(self.tz)
        self.since = self.now - timedelta(days=days)
    def local(self, dt):
        return dt.astimezone(self.tz) if self.tz else dt.astimezone()
    def fmt(self, dt): return self.local(dt).isoformat(timespec="seconds")
    def in_window(self, dt): return dt is not None and self.since <= dt <= self.now + timedelta(days=1)

def webkit_dt(us):
    if not us or us <= 0: return None
    try: return WEBKIT_EPOCH + timedelta(microseconds=int(us))
    except (OverflowError, ValueError): return None
def filetime_dt(ft):
    if not ft or ft <= 0: return None
    try: return WEBKIT_EPOCH + timedelta(microseconds=int(ft) // 10)
    except (OverflowError, ValueError): return None
def unix_us_dt(us):
    if not us or us <= 0: return None
    try: return datetime.fromtimestamp(int(us) / 1e6, UTC)
    except (OverflowError, ValueError, OSError): return None
def unix_dt(s):
    try: return datetime.fromtimestamp(s, UTC)
    except (OverflowError, ValueError, OSError): return None

# ------------------------------------------------------------------ 路径
WIN_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
def pmod(p):
    """Windows 风格的路径字符串（来自数据库/快捷方式）一律用 ntpath 处理，哪怕脚本跑在 Linux 上测试。"""
    return ntpath if (IS_WIN or WIN_ABS.match(p) or "\\" in p) else posixpath

class PathMapper:
    """事件里的 path：在用户主目录下 → “用户名/Documents/x.xlsx”（与 recorder_win 一致，相对主目录的上一级）；
    其它盘 → “E:/项目/x.xlsx”。一律用正斜杠。"""
    def __init__(self, home, aliases=()):
        self.homes = []
        for h in [home, *aliases]:
            if not h: continue
            m = pmod(h); h2 = m.normpath(h).rstrip("\\/")
            self.homes.append((m, h2))
        self.home_name = pmod(home).basename(pmod(home).normpath(home).rstrip("\\/")) if home else "user"
    def __call__(self, p):
        if not p: return None
        m = pmod(p); p2 = m.normpath(p)
        for hm, h in self.homes:
            if hm is not m: continue
            a, b = (p2.lower(), h.lower()) if m is ntpath else (p2, h)
            if a == b or a.startswith(b + m.sep):
                rest = p2[len(h):].lstrip("\\/")
                return self.home_name + "/" + rest.replace("\\", "/")
        return p2.replace("\\", "/")

def file_url_to_path(u):
    """file:///C:/Users/x/a.pdf -> C:\\Users\\x\\a.pdf"""
    if not u.lower().startswith("file:"): return None
    s = unquote(urlsplit(u).path)
    if re.match(r"^/[A-Za-z]:", s): return s[1:].replace("/", "\\")
    return s

def clean_url(u, mode):
    if not u: return u
    try: sp = urlsplit(u)
    except ValueError: return None
    if sp.scheme == "file": return u
    if mode == "host": return f"{sp.scheme}://{sp.hostname or ''}/"
    if mode == "path": return urlunsplit((sp.scheme, sp.netloc.split("@")[-1], sp.path, "", ""))
    q = [(k, "REDACTED" if SENSITIVE_PARAM.match(k) else v) for k, v in parse_qsl(sp.query, keep_blank_values=True)]
    return urlunsplit((sp.scheme, sp.netloc.split("@")[-1], sp.path, urlencode(q, safe="/:"), ""))  # 去掉 user:pass@ 和 #片段

# ------------------------------------------------------------------ 日志
class Log:
    def __init__(self): self.lines = []; self.counts = Counter()
    def __call__(self, msg):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"; self.lines.append(line); print(line, file=sys.stderr)

# ------------------------------------------------------------------ SQLite：复制后只读打开
def open_copy(src, tmpdir, log):
    """浏览器运行时数据库被锁：先复制（连同 -wal/-journal）到临时目录；复制失败再试 immutable 只读打开原文件。"""
    name = os.path.basename(src)
    if name.lower() in NEVER_TOUCH: raise RuntimeError("refuse")
    dst = os.path.join(tmpdir, f"{int(time.time()*1000)}_{name}")
    try:
        shutil.copyfile(src, dst)
        for suf in ("-wal", "-journal"):
            if os.path.exists(src + suf):
                try: shutil.copyfile(src + suf, dst + suf)
                except OSError: pass
        con = sqlite3.connect(Path(dst).as_uri() + "?mode=ro", uri=True)
        return con, dst
    except (OSError, sqlite3.Error) as ex:
        log(f"  复制 {src} 失败（{ex.__class__.__name__}），改为只读 immutable 方式直接打开")
        con = sqlite3.connect(Path(src).as_uri() + "?mode=ro&immutable=1", uri=True)
        return con, None

def drop_copy(con, dst):
    try: con.close()
    except Exception: pass
    if dst:
        for suf in ("", "-wal", "-journal", "-shm"):
            try: os.remove(dst + suf)
            except OSError: pass

def cols(con, table):
    try: return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error: return set()

# ------------------------------------------------------------------ 1. 浏览器
def scan_dirs(base, depth):
    """列出 base 下 depth 层以内的目录（只列目录名，不进入文件内容）。"""
    out, frontier = [], [(base, 0)]
    while frontier:
        d, k = frontier.pop()
        if k >= depth: continue
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            out.append((e.path, k + 1)); frontier.append((e.path, k + 1))
                    except OSError: continue
        except OSError: continue
    return out

def browser_label(path, base):
    rel = os.path.relpath(path, base).replace("\\", "/").lower()
    for key, lab in (("tabbit", "tabbit"), ("microsoft/edge", "edge"), ("google/chrome", "chrome"), ("bravesoftware", "brave"),
                     ("chromium", "chromium"), ("vivaldi", "vivaldi"), ("opera", "opera"), ("360", "360"), ("qqbrowser", "qq"),
                     ("sogou", "sogou")):
        if key in rel: return lab
    # 不是独立浏览器：自动化/测试浏览器（不是人在用）和应用内嵌的 WebView 外壳（Steam、代理客户端、桌面 App）分开标出来，
    # 否则它们的 profile 目录都叫 Default，会全部混成一个 "default" 来源
    parts = [x for x in rel.split("/") if x and x not in (".", "..")]
    app_dir = re.sub(r"[^a-z0-9]+", "-", parts[0] if parts else "").strip("-")
    if re.search(r"playwright|puppeteer|selenium|webdriver|cypress|burpsuite|pre-wired-browser|chrome-for-testing|headless", rel):
        return "automation-" + (app_dir or "browser")
    if re.search(r"ebwebview|htmlcache|cefcache|qtcef|webview2|electron", rel) or (parts and parts[-1] in ("default",) and "user data" not in rel):
        return "appshell-" + (app_dir or "app")
    return re.sub(r"[^a-z0-9]+", "-", rel.split("/user data")[0].split("/")[-1]).strip("-") or "chromium-like"

def find_chromium_profiles(localappdata, appdata, extra, log):
    found = []
    seen = set()
    def add_userdata(ud, label):
        try: entries = list(os.scandir(ud))
        except OSError: return
        for e in entries:
            if e.is_dir() and os.path.isfile(os.path.join(e.path, "History")) and e.name not in ("System Profile", "Guest Profile"):
                key = os.path.normcase(os.path.abspath(e.path))
                if key not in seen: seen.add(key); found.append((label, e.name, e.path))
    for base in (localappdata, appdata):
        if not base or not os.path.isdir(base): continue
        for d, k in scan_dirs(base, 3):
            n = os.path.basename(d)
            if n.lower() == "user data":
                add_userdata(d, browser_label(d, base))
            elif os.path.isfile(os.path.join(d, "History")) and os.path.isfile(os.path.join(d, "Preferences")) and k <= 3:
                key = os.path.normcase(os.path.abspath(d))   # Opera 这类：目录本身就是 profile
                if key not in seen and "user data" not in d.lower():
                    seen.add(key); found.append((browser_label(d, base), n, d))
    for ud in extra or []:
        if os.path.isfile(os.path.join(ud, "History")):
            seen.add(os.path.normcase(os.path.abspath(ud))); found.append((browser_label(ud, os.path.dirname(ud)), os.path.basename(ud), ud))
        else: add_userdata(ud, browser_label(ud, os.path.dirname(ud)))
    return found

def read_chromium(label, prof_name, prof_dir, ctx):
    log, clk, emit = ctx["log"], ctx["clock"], ctx["emit"]
    app = BROWSER_APP.get(label, label)
    src = f"backfill:{label}"
    con, dst = open_copy(os.path.join(prof_dir, "History"), ctx["tmp"], log)
    nv = nd = 0
    try:
        since_us = int((clk.since - WEBKIT_EPOCH).total_seconds() * 1e6)
        vc = cols(con, "visits")
        dur = "v.visit_duration" if "visit_duration" in vc else "0"
        frm = "v.from_visit" if "from_visit" in vc else "0"
        rows = con.execute(f"SELECT v.id, v.visit_time, {dur}, v.transition, u.url, u.title, {frm} FROM visits v "
                           f"JOIN urls u ON v.url = u.id WHERE v.visit_time >= ? ORDER BY v.visit_time", (since_us,)).fetchall()
        # 重定向链只保留终点：如果下一条访问是从这一条重定向过来的（from_visit=本条，且带重定向标记），丢掉本条
        redirected_from = {r[6] for r in rows if (r[3] & 0xC0000000) and r[6]}
        for vid, vt, vdur, tr, url, title, _ in rows:
            core = tr & 0xFF
            if core in (3, 4) or vid in redirected_from: continue
            if not url or url.startswith(SKIP_URL): continue
            dt = webkit_dt(vt)
            if not clk.in_window(dt): continue
            fpath = file_url_to_path(url) if url.startswith("file:") else None
            emit({"ts": clk.fmt(dt), "type": "focus", "app": app, "title": title or "", "url": clean_url(url, ctx["url_mode"]),
                  "dur_s": int((vdur or 0) / 1e6), "transition": CHROME_CORE.get(core, str(core)), "browser_profile": prof_name, "source": src})
            nv += 1
            if fpath and os.path.splitext(fpath)[1].lower() in DOC_EXT:   # 在浏览器里打开的本地 PDF 等
                emit({"ts": clk.fmt(dt), "type": "file_open", "path": ctx["mapper"](fpath), "app": app, "source": src})
        dc = cols(con, "downloads")
        if dc:
            want = [c for c in ("id", "target_path", "current_path", "start_time", "end_time", "received_bytes", "total_bytes",
                                "state", "tab_url", "referrer", "mime_type", "site_url") if c in dc]
            chains = {}
            if cols(con, "downloads_url_chains"):
                for did, idx, u in con.execute("SELECT id, chain_index, url FROM downloads_url_chains ORDER BY id, chain_index"):
                    chains.setdefault(did, []).append(u)
            for r in con.execute(f"SELECT {', '.join(want)} FROM downloads WHERE start_time >= ?", (since_us,)):
                d = dict(zip(want, r))
                dt = webkit_dt(d.get("end_time")) or webkit_dt(d.get("start_time"))
                if not clk.in_window(dt): continue
                tp = d.get("target_path") or d.get("current_path")
                if not tp: continue
                ch = chains.get(d.get("id"), [])
                srcu = d.get("tab_url") or d.get("referrer") or d.get("site_url") or (ch[0] if ch else None)
                st = {1: "complete", 2: "cancelled", 3: "interrupted"}.get(d.get("state"), "in_progress")
                emit({"ts": clk.fmt(dt), "type": "file_create", "path": ctx["mapper"](tp), "app": app,
                      "source_url": clean_url(srcu, ctx["url_mode"]) if srcu else None,
                      "file_url": clean_url(ch[-1], ctx["url_mode"]) if ch else None,
                      "size": d.get("received_bytes"), "download_state": st, "exists_now": os.path.exists(tp) if IS_WIN or not WIN_ABS.match(tp) else None,
                      "source": src + "-downloads"})
                nd += 1
    finally:
        drop_copy(con, dst)
    log(f"  {label}/{prof_name}: 网页访问 {nv} 条，下载 {nd} 条")
    ctx["log"].counts[src] += nv; ctx["log"].counts[src + "-downloads"] += nd

def find_firefox(appdata):
    base = os.path.join(appdata or "", "Mozilla", "Firefox", "Profiles")
    if not os.path.isdir(base): return []
    return [e.path for e in os.scandir(base) if e.is_dir() and os.path.isfile(os.path.join(e.path, "places.sqlite"))]

def read_firefox(prof_dir, ctx):
    log, clk, emit = ctx["log"], ctx["clock"], ctx["emit"]
    con, dst = open_copy(os.path.join(prof_dir, "places.sqlite"), ctx["tmp"], log)
    nv = nd = 0
    try:
        since_us = int(clk.since.timestamp() * 1e6)
        for vd, vt, url, title in con.execute("SELECT v.visit_date, v.visit_type, p.url, p.title FROM moz_historyvisits v "
                                              "JOIN moz_places p ON v.place_id = p.id WHERE v.visit_date >= ? ORDER BY v.visit_date", (since_us,)):
            if vt in (4, 5, 6, 8) or not url or url.startswith(SKIP_URL): continue
            dt = unix_us_dt(vd)
            if not clk.in_window(dt): continue
            emit({"ts": clk.fmt(dt), "type": "focus", "app": "firefox", "title": title or "", "url": clean_url(url, ctx["url_mode"]),
                  "dur_s": 0, "transition": FF_TYPE.get(vt, str(vt)), "browser_profile": os.path.basename(prof_dir), "source": "backfill:firefox"})
            nv += 1
        if cols(con, "moz_annos") and cols(con, "moz_anno_attributes"):
            q = ("SELECT a.content, a.dateAdded, p.url FROM moz_annos a JOIN moz_anno_attributes n ON a.anno_attribute_id = n.id "
                 "JOIN moz_places p ON a.place_id = p.id WHERE n.name = 'downloads/destinationFileURI' AND a.dateAdded >= ?")
            for content, added, url in con.execute(q, (since_us,)):
                dt = unix_us_dt(added); tp = file_url_to_path(content or "")
                if not tp or not clk.in_window(dt): continue
                emit({"ts": clk.fmt(dt), "type": "file_create", "path": ctx["mapper"](tp), "app": "firefox",
                      "source_url": clean_url(url, ctx["url_mode"]), "source": "backfill:firefox-downloads"})
                nd += 1
    finally:
        drop_copy(con, dst)
    log(f"  firefox/{os.path.basename(prof_dir)}: 网页访问 {nv} 条，下载 {nd} 条")
    ctx["log"].counts["backfill:firefox"] += nv; ctx["log"].counts["backfill:firefox-downloads"] += nd

# ------------------------------------------------------------------ 2. 最近使用（.lnk）与 Office MRU
def _cstr(b, off, enc):
    end = b.index(b"\x00", off); return b[off:end].decode(enc, "replace")
def _wstr(b, off):
    end = off
    while end + 1 < len(b) and b[end:end + 2] != b"\x00\x00": end += 2
    return b[off:end].decode("utf-16-le", "replace")

def parse_lnk(data, ansi="mbcs" if IS_WIN else "gbk"):
    """按 [MS-SHLLINK] 解析 .lnk：返回 {target, is_dir, ctime, atime, wtime, size}；解析不了返回 None。"""
    if len(data) < 0x4C or data[:4] != b"\x4c\x00\x00\x00": return None
    flags, attrs = struct.unpack_from("<II", data, 0x14)
    ct, at, wt = struct.unpack_from("<QQQ", data, 0x1C)
    size = struct.unpack_from("<I", data, 0x34)[0]
    off = 0x4C; target = None
    try:
        if flags & 0x1:
            off += 2 + struct.unpack_from("<H", data, off)[0]
        if flags & 0x2:
            li_size, li_hsize, li_flags, _vol, lbp, cnrl, cps = struct.unpack_from("<7I", data, off)
            lbp_u = cps_u = 0
            if li_hsize >= 0x24: lbp_u, cps_u = struct.unpack_from("<2I", data, off + 28)
            suffix = (_wstr(data, off + cps_u) if cps_u else (_cstr(data, off + cps, ansi) if cps else ""))
            if li_flags & 0x1:
                base = _wstr(data, off + lbp_u) if lbp_u else _cstr(data, off + lbp, ansi)
                target = base + suffix
            elif li_flags & 0x2 and cnrl:
                net_off = struct.unpack_from("<I", data, off + cnrl + 8)[0]
                share = _cstr(data, off + cnrl + net_off, ansi)
                target = share.rstrip("\\") + ("\\" + suffix if suffix else "")
            off += li_size
        if target is None and flags & 0x8 | flags & 0x10:   # 没有 LinkInfo：用 StringData 里的 工作目录+相对路径 拼
            uni = bool(flags & 0x80); strs = {}
            for bit, name in ((0x4, "name"), (0x8, "rel"), (0x10, "wd"), (0x20, "args"), (0x40, "icon")):
                if flags & bit:
                    n = struct.unpack_from("<H", data, off)[0]; off += 2
                    raw = data[off:off + (n * 2 if uni else n)]; off += n * 2 if uni else n
                    strs[name] = raw.decode("utf-16-le" if uni else ansi, "replace")
            if strs.get("wd") and strs.get("rel"):
                target = ntpath.normpath(ntpath.join(strs["wd"], strs["rel"]))
    except (struct.error, ValueError, IndexError):
        pass
    return {"target": target, "is_dir": bool(attrs & 0x10), "ctime": filetime_dt(ct), "atime": filetime_dt(at),
            "wtime": filetime_dt(wt), "size": size}

def read_recent(appdata, ctx):
    log, clk, emit = ctx["log"], ctx["clock"], ctx["emit"]
    d = os.path.join(appdata or "", "Microsoft", "Windows", "Recent")
    if not os.path.isdir(d): log("  没找到“最近使用”文件夹，跳过"); return
    n = bad = 0
    for e in os.scandir(d):
        if not e.name.lower().endswith(".lnk") or not e.is_file(): continue
        try:
            with open(e.path, "rb") as f: info = parse_lnk(f.read(64 * 1024))
            st = e.stat()
        except OSError: bad += 1; continue
        if not info: bad += 1; continue
        target = info["target"]
        if not target:   # 解析不出路径时，只能用快捷方式名（“报告.docx.lnk” -> “报告.docx”）
            stem = e.name[:-4]
            if "." not in stem: continue
            target = stem
        if info["is_dir"]: continue
        ext = pmod(target).splitext(target)[1].lower()
        if not ext: continue
        path = ctx["mapper"](target) if WIN_ABS.match(target) else target
        last = unix_dt(st.st_mtime)                     # 快捷方式最后更新 = 最后一次打开
        first = unix_dt(getattr(st, "st_birthtime", st.st_ctime)) if IS_WIN or hasattr(st, "st_birthtime") else None
        app = EXT_APP.get(ext, "explorer")
        for t, how in ((last, "last"), (first, "first")):
            if t and clk.in_window(t) and not (how == "first" and last and abs((last - t).total_seconds()) < 3600):
                emit({"ts": clk.fmt(t), "type": "file_open", "path": path, "app": app, "open": how, "source": "backfill:recent"}); n += 1
        wt = info["wtime"]   # 打开那一刻目标文件的修改时间：落在窗口里就当作一次保存
        if wt and clk.in_window(wt) and ext in DOC_EXT:
            emit({"ts": clk.fmt(wt), "type": "file_save", "path": path, "app": app, "size": info["size"], "source": "backfill:recent-target"})
            n += 1
    log(f"  最近使用（.lnk）：{n} 条事件" + (f"，{bad} 个快捷方式解析失败" if bad else ""))
    ctx["log"].counts["backfill:recent"] += n

MRU_RE = re.compile(r"\[T([0-9A-Fa-f]{16})\](?:\[[^\]]*\])*\*(.+)$")
def parse_office_mru(value):
    """'[F00000000][T01DA2B3C4D5E6F70][O00000000]*C:\\a\\b.docx' -> (datetime, path)"""
    m = MRU_RE.search(value or "")
    if not m: return None
    return filetime_dt(int(m.group(1), 16)), m.group(2)

def read_office_mru(ctx):
    if not IS_WIN: ctx["log"]("  Office 最近使用：不是 Windows，跳过"); return
    import winreg
    log, clk, emit = ctx["log"], ctx["clock"], ctx["emit"]; n = 0
    def values(k):
        i = 0
        while True:
            try: yield winreg.EnumValue(k, i); i += 1
            except OSError: return
    def subkeys(k):
        i = 0
        while True:
            try: yield winreg.EnumKey(k, i); i += 1
            except OSError: return
    try: off = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Office", 0, winreg.KEY_READ)
    except OSError: log("  没装 Office（或从没用过），跳过 Office 最近使用"); return
    for ver in list(subkeys(off)):
        for appname, app in (("Word", "word"), ("Excel", "excel"), ("PowerPoint", "powerpoint")):
            bases = [rf"{ver}\{appname}\File MRU"]
            try:
                with winreg.OpenKey(off, rf"{ver}\{appname}\User MRU") as um:
                    bases += [rf"{ver}\{appname}\User MRU\{s}\File MRU" for s in list(subkeys(um))]
            except OSError: pass
            for b in bases:
                try:
                    with winreg.OpenKey(off, b) as k:
                        for name, val, _ in list(values(k)):
                            r = parse_office_mru(val) if isinstance(val, str) else None
                            if r and clk.in_window(r[0]):
                                emit({"ts": clk.fmt(r[0]), "type": "file_open", "path": ctx["mapper"](r[1]), "app": app, "source": "backfill:office-mru"}); n += 1
                except OSError: continue
    log(f"  Office 最近使用：{n} 条"); ctx["log"].counts["backfill:office-mru"] += n

# ------------------------------------------------------------------ 3. 文件夹元数据
def known_folders(home):
    out = {"Documents": os.path.join(home, "Documents"), "Desktop": os.path.join(home, "Desktop"), "Downloads": os.path.join(home, "Downloads")}
    if IS_WIN:   # 文档/桌面/下载可能被挪到别的盘（比如 D:\文档），以注册表为准
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                for name, key in (("Documents", "Personal"), ("Desktop", "Desktop"), ("Downloads", "{374DE290-123F-4565-9164-39C4925E467B}")):
                    try: out[name] = os.path.expandvars(winreg.QueryValueEx(k, key)[0])
                    except OSError: pass
        except OSError: pass
    od = os.path.join(home, "OneDrive")
    if os.path.isdir(od): out["OneDrive"] = od
    return out

def scan_files(roots, ctx, max_depth, max_files, exclude):
    log, clk, emit = ctx["log"], ctx["clock"], ctx["emit"]
    seen_dirs, n_files, n_ev, hit_cap = set(), 0, 0, False
    found = []
    excl = [os.path.normcase(os.path.abspath(x)) for x in exclude if x]
    for root in roots:
        if not os.path.isdir(root): log(f"  文件夹不存在，跳过：{root}"); continue
        root_depth = os.path.abspath(root).rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            key = os.path.normcase(os.path.abspath(dirpath))
            if key in seen_dirs or any(key == x or key.startswith(x + os.sep) for x in excl):
                dirnames[:] = []; continue
            seen_dirs.add(key)
            depth = os.path.abspath(dirpath).rstrip("\\/").count(os.sep) - root_depth
            dirnames[:] = [d for d in dirnames if depth < max_depth and d.lower() not in SKIP_DIRS
                           and not d.startswith((".", "$", "~")) and not os.path.islink(os.path.join(dirpath, d))]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in DOC_EXT or fn.startswith(("~$", ".~", "~WRL")): continue
                n_files += 1
                if n_files > max_files: hit_cap = True; break
                p = os.path.join(dirpath, fn)
                try: st = os.stat(p)
                except OSError: continue
                mt = unix_dt(st.st_mtime)
                bt = unix_dt(st.st_birthtime) if hasattr(st, "st_birthtime") else (unix_dt(st.st_ctime) if IS_WIN else None)
                rel = ctx["mapper"](p); app = EXT_APP.get(ext, "explorer")
                if bt and clk.in_window(bt):
                    emit({"ts": clk.fmt(bt), "type": "file_create", "path": rel, "app": app, "size": st.st_size, "source": "backfill:fs"}); n_ev += 1
                if mt and clk.in_window(mt):
                    ev = {"ts": clk.fmt(mt), "type": "file_save", "path": rel, "app": app, "size": st.st_size, "source": "backfill:fs"}
                    if bt and mt < bt - timedelta(seconds=5): ev["copied"] = True   # 修改时间早于创建时间：是复制/解压来的
                    emit(ev); n_ev += 1
                    found.append((mt, p, rel, ext, st.st_size))
            if hit_cap: break
        if hit_cap: break
    log(f"  文件夹：看过 {min(n_files, max_files)} 个文档类文件，{n_ev} 条事件" + ("（达到 --max-files 上限，后面的没扫）" if hit_cap else ""))
    ctx["log"].counts["backfill:fs"] += n_ev
    return found

def copy_content(found, out_dir, log, max_files, max_mb):
    """--with-content：只复制，不改原文件。按最近修改优先，受数量和总大小限制。"""
    cdir = os.path.join(out_dir, "content"); os.makedirs(cdir, exist_ok=True)
    manifest, total = [], 0
    for mt, p, rel, ext, size in sorted(found, reverse=True):
        if ext not in CONTENT_EXT or size > 20 * 1024 * 1024: continue
        if len(manifest) >= max_files or total + size > max_mb * 1024 * 1024: break
        name = f"{len(manifest):05d}{ext}"
        try: shutil.copyfile(p, os.path.join(cdir, name))
        except OSError as ex: log(f"  复制失败 {rel}：{ex.__class__.__name__}"); continue
        manifest.append({"path": rel, "stored": f"content/{name}", "size": size}); total += size
    with open(os.path.join(out_dir, "content_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    log(f"  --with-content：复制了 {len(manifest)} 个文件，共 {total/1024/1024:.1f} MB 到 {cdir}")

# ------------------------------------------------------------------ 主程序
def read_vscode_recent(appdata, ctx):
    """VS Code / Cursor 最近打开的工作区与文件（globalStorage/storage.json），只读。"""
    n = 0
    log, clk, emit = ctx["log"], ctx["clock"], ctx["emit"]
    for product, app in (("Code", "code"), ("Cursor", "cursor"), ("Code - Insiders", "code")):
        path = os.path.join(appdata, product, "User", "globalStorage", "storage.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as ex:
            log(f"  editor {product}: skip ({ex})"); continue
        for m in re.finditer(r'"(?:folder|file)(?:Uri)?":\s*"([^"]+)"', text):
            raw = m.group(1).replace("file:///", "").replace("%3A", ":")
            if len(raw) < 3: continue
            path_m = ctx["mapper"](raw) if WIN_ABS.match(raw) or raw.startswith("\\\\") else raw
            emit({"ts": clk.fmt(clk.now), "type": "file_open", "path": path_m, "app": app,
                  "source": f"backfill:vscode-{app}"}); n += 1
    log(f"  编辑器最近: {n} 条"); log.counts["backfill:vscode"] += n


def read_git_repos(roots, ctx, max_repos=6, max_commits=40):
    """在 --roots 下发现 .git，导出近期 commit（只读 git log）。"""
    import subprocess
    n = 0; repos = []
    log, clk, emit = ctx["log"], ctx["clock"], ctx["emit"]
    cutoff = clk.since.replace(tzinfo=None)
    for root in roots:
        if not root or not os.path.isdir(root): continue
        for dirpath, dirnames, filenames in os.walk(root):
            if ".git" in dirnames or ".git" in filenames:
                if any(x in dirpath for x in ("node_modules", ".venv", "AppData")):
                    dirnames[:] = []; continue
                repos.append(dirpath)
                dirnames[:] = []
            if len(repos) >= max_repos: break
        if len(repos) >= max_repos: break
    for repo in repos[:max_repos]:
        try:
            r = subprocess.run(["git", "-C", repo, "log", f"-n{max_commits}", "--pretty=format:%aI\t%s"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode != 0: continue
            for line in r.stdout.splitlines():
                if "\t" not in line: continue
                ts, subj = line.split("\t", 1)
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    continue
                if dt.replace(tzinfo=None) < cutoff: continue
                emit({"ts": clk.fmt(dt), "type": "git_commit", "path": ctx["mapper"](repo),
                      "app": "git", "title": subj[:200], "source": "backfill:git"}); n += 1
        except Exception as ex:
            log(f"  git {repo}: {ex}")
    log(f"  Git 提交: {n} 条 / {len(repos)} 仓"); log.counts["backfill:git"] += n



def main(argv=None):
    env = os.environ
    home_default = env.get("USERPROFILE") or os.path.expanduser("~")
    ap = argparse.ArgumentParser(description="OpenLookout 历史回溯导入（只读）")
    ap.add_argument("--out", default=r"E:\OpenLookout\data\backfill" if IS_WIN else "./backfill_out", help="输出目录（只会往这里写）")
    ap.add_argument("--days", type=int, default=90, help="回看多少天，默认 90")
    ap.add_argument("--roots", action="append", default=[], help="额外要扫描的文件夹，可写多次，比如 --roots E:\\ --roots D:\\项目")
    ap.add_argument("--no-default-folders", action="store_true", help="不扫 文档/桌面/下载")
    ap.add_argument("--max-depth", type=int, default=6); ap.add_argument("--max-files", type=int, default=50000)
    ap.add_argument("--skip", action="append", default=[], choices=["browser", "recent", "office", "files", "vscode", "git"], help="跳过某类来源")
    ap.add_argument("--browser-dir", action="append", default=[], help="手动指定浏览器的 User Data 或 profile 目录")
    ap.add_argument("--url-detail", choices=["full", "path", "host"], default="full",
                    help="网址保留多少：full=完整（敏感参数值会被抹掉），path=去掉查询参数，host=只留域名")
    ap.add_argument("--with-content", action="store_true", help="额外复制近期表格/文本文件到 out\\content（默认不复制）")
    ap.add_argument("--content-max-files", type=int, default=300); ap.add_argument("--content-max-mb", type=int, default=500)
    ap.add_argument("--plan", action="store_true", help="只列出会读哪些来源，不读任何数据")
    ap.add_argument("--tz", default=None, help="时区，比如 +08:00；默认用系统时区")
    # 下面几个只给测试用（在 Linux 上用假目录模拟 Windows）
    ap.add_argument("--home", default=home_default, help=argparse.SUPPRESS)
    ap.add_argument("--home-alias", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--localappdata", default=env.get("LOCALAPPDATA") or os.path.join(home_default, "AppData", "Local"), help=argparse.SUPPRESS)
    ap.add_argument("--appdata", default=env.get("APPDATA") or os.path.join(home_default, "AppData", "Roaming"), help=argparse.SUPPRESS)
    ap.add_argument("--now", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    try: sys.stderr.reconfigure(errors="replace")   # 控制台编码不是 UTF-8 时别因为中文崩掉
    except Exception: pass

    log = Log(); clk = Clock(a.tz, a.now, a.days)
    folders = {} if a.no_default_folders else known_folders(a.home)
    roots = list(dict.fromkeys(list(folders.values()) + a.roots))
    profiles = [] if "browser" in a.skip else find_chromium_profiles(a.localappdata, a.appdata, a.browser_dir, log)
    ff = [] if "browser" in a.skip else find_firefox(a.appdata)
    log(f"OpenLookout 历史回溯 v{VERSION}：回看 {a.days} 天（{clk.local(clk.since):%Y-%m-%d} 起），输出到 {a.out}")
    log("会读取的来源：")
    for lab, pn, pd in profiles: log(f"  浏览器 {lab}/{pn}: {os.path.join(pd, 'History')}（只读这个文件）")
    for pd in ff: log(f"  浏览器 firefox: {os.path.join(pd, 'places.sqlite')}")
    if not profiles and not ff and "browser" not in a.skip: log("  （没找到浏览器历史）")
    if "recent" not in a.skip: log(f"  最近使用: {os.path.join(a.appdata, 'Microsoft', 'Windows', 'Recent')}")
    if "office" not in a.skip: log("  Office 最近使用: 注册表 HKCU\\Software\\Microsoft\\Office\\*\\File MRU（只读）")
    if "files" not in a.skip:
        for r in roots: log(f"  文件夹（只看文件名、时间、大小）: {r}")
    if a.with_content: log("  --with-content：会把近期表格/文本文件复制一份到输出目录")
    if a.plan:
        log("--plan：到此为止，没有读取任何数据。"); return 0

    out = os.path.abspath(a.out); os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "_tmp"); os.makedirs(tmp, exist_ok=True)
    events = []
    def emit(e): events.append({k: v for k, v in e.items() if v is not None})
    ctx = {"log": log, "clock": clk, "emit": emit, "tmp": tmp, "url_mode": a.url_detail, "mapper": PathMapper(a.home, a.home_alias)}
    try:
        for lab, pn, pd in profiles:
            try: read_chromium(lab, pn, pd, ctx)
            except Exception as ex: log(f"  {lab}/{pn} 读取失败：{ex.__class__.__name__}: {str(ex)[:120]}（可以关掉浏览器再试）")
        for pd in ff:
            try: read_firefox(pd, ctx)
            except Exception as ex: log(f"  firefox 读取失败：{ex.__class__.__name__}: {str(ex)[:120]}")
        if "recent" not in a.skip:
            try: read_recent(a.appdata, ctx)
            except Exception as ex: log(f"  最近使用读取失败：{ex}")
        if "office" not in a.skip:
            try: read_office_mru(ctx)
            except Exception as ex: log(f"  Office 最近使用读取失败：{ex}")
        found = []
        if "files" not in a.skip:
            found = scan_files(roots, ctx, a.max_depth, a.max_files, exclude=[out])
        if "vscode" not in a.skip:
            try: read_vscode_recent(a.appdata, ctx)
            except Exception as ex: log(f"  编辑器最近读取失败：{ex}")
        if "git" not in a.skip:
            try: read_git_repos(roots, ctx)
            except Exception as ex: log(f"  Git 历史读取失败：{ex}")
        if a.with_content and found:
            copy_content(found, out, log, a.content_max_files, a.content_max_mb)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 去重 + 按时间排序
    uniq, seen = [], set()
    for e in events:
        k = (e["ts"], e["type"], e.get("path"), e.get("url"), e.get("source"))
        if k in seen: continue
        seen.add(k); uniq.append(e)
    uniq.sort(key=lambda e: datetime.fromisoformat(e["ts"]))
    with open(os.path.join(out, "events.jsonl"), "w", encoding="utf-8") as f:
        for e in uniq: f.write(json.dumps(e, ensure_ascii=False) + "\n")
    by_type = Counter(e["type"] for e in uniq); by_src = Counter(e["source"] for e in uniq)
    meta = {"now": clk.local(clk.now).replace(tzinfo=None).isoformat(timespec="seconds"),
            "user_home": PathMapper(a.home).home_name, "watched_dirs": ["Documents", "Desktop", "Downloads"], "user_aliases": [],
            "mode": "backfill",
            "source": {"dataset": "backfill_win", "version": VERSION, "lookback_days": a.days,
                       "since": clk.local(clk.since).isoformat(timespec="seconds"), "url_detail": a.url_detail,
                       "with_content": a.with_content, "events": len(uniq), "by_type": dict(by_type), "by_source": dict(by_src),
                       "gaps": ["no clipboard / window-focus events (history only)", "browser visits are page loads, not focus time",
                                "file_save is the LAST modification time only (one per file), plus Recent .lnk target times",
                                "vscode/cursor recent and git log are best-effort extras for scaling behavior traces"]}}
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f: json.dump(meta, f, ensure_ascii=False, indent=1)
    log(f"完成：{len(uniq)} 条事件 → {os.path.join(out, 'events.jsonl')}")
    for k, v in sorted(by_src.items()): log(f"  {k}: {v}")
    with open(os.path.join(out, "backfill_log.txt"), "w", encoding="utf-8") as f: f.write("\n".join(log.lines) + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
