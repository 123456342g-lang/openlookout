"""端到端测试：造假目录 → 在审计钩子下跑 backfill_win.main() → 检查输出、隐私和只读。
python3 tests/test_backfill.py"""
import json, ntpath, os, sys, hashlib, tempfile
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import backfill_win as bw, make_fixture

ROOT = tempfile.mkdtemp(prefix="bf_fx_")   # 系统临时目录：Windows/Linux 通用；目录名不含 "OpenLookout"，避免路径断言误报
H = f"{ROOT}/C/Users/xiaoming"; OUT = f"{ROOT}/E/OpenLookout/data/backfill"
fails = []
def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond: fails.append(msg)

# ---------- 1. 纯函数：Windows 路径、时间、.lnk、Office MRU
print("[unit]")
m = bw.PathMapper("C:\\Users\\xiaoming")
check(m("C:\\Users\\xiaoming\\Documents\\周报\\a.xlsx") == "xiaoming/Documents/周报/a.xlsx", "ntpath: 主目录下 -> 用户名/...")
check(m("c:\\users\\XIAOMING\\Downloads\\b.pdf") == "xiaoming/Downloads/b.pdf", "ntpath: 大小写不敏感")
check(m("E:\\项目\\数据\\x.csv") == "E:/项目/数据/x.csv", "ntpath: 其它盘 -> E:/...")
check(m("C:\\Users\\xiaomingX\\a.txt") == "C:/Users/xiaomingX/a.txt", "ntpath: 前缀相同但不是主目录")
check(m("\\\\NAS\\share\\a.docx") == "//NAS/share/a.docx", "ntpath: UNC 路径")
win_ok = bw.pmod("C:\\a") is ntpath
posix_ok = (not bw.IS_WIN and bw.pmod("/tmp/a") is not ntpath) or (bw.IS_WIN and bw.pmod("/tmp/a") is ntpath)
check(win_ok and posix_ok, "pmod 选对模块")
check(bw.file_url_to_path("file:///C:/Users/x/%E8%AE%BA%E6%96%87.pdf") == "C:\\Users\\x\\论文.pdf", "file:// -> Windows 路径")
check(bw.webkit_dt(13372473600000000).isoformat() == "2024-10-04T00:00:00+00:00", "WebKit 时间换算")
check(bw.filetime_dt(133724736000000000).isoformat() == "2024-10-04T00:00:00+00:00", "FILETIME 换算")
check("REDACTED" in bw.clean_url("https://a.cn/x?token=abc&week=3#frag", "full") and "week=3" in bw.clean_url("https://a.cn/x?token=abc&week=3", "full")
      and "#" not in bw.clean_url("https://a.cn/x#frag", "full"), "网址：敏感参数抹掉、片段去掉")
check(bw.clean_url("https://u:p@a.cn/x?q=1", "path") == "https://a.cn/x", "网址：path 模式去掉账号和参数")
r = bw.parse_office_mru("[F00000000][T01DB15F0A2B3C400][O00000000]*D:\\工作\\预算.xlsx")
check(r and r[1] == "D:\\工作\\预算.xlsx" and r[0].year >= 2024, "Office MRU 解析")
t0 = make_fixture.T("2026-09-01T10:00:00")
for uni in (True, False):
    info = bw.parse_lnk(make_fixture.lnk_bytes("C:\\Users\\xiaoming\\文档\\报告.docx", t0, t0, 1, unicode=uni))
    check(info and info["target"] == "C:\\Users\\xiaoming\\文档\\报告.docx" and info["wtime"] == t0, f".lnk 解析（{'Unicode' if uni else 'ANSI/GBK'}）")
check(bw.parse_lnk(b"garbage") is None, ".lnk 坏文件返回 None")

# ---------- 2. 端到端（审计钩子：记录所有打开的文件、网络连接）
print("[e2e]")
make_fixture.main(ROOT)
def digest(root):
    out = {}
    out_norm = os.path.normpath(OUT)
    for dp, dn, fn in os.walk(root):
        if os.path.normpath(dp).startswith(out_norm): continue
        for f in fn:
            p = os.path.join(dp, f); st = os.stat(p)
            out[p] = (st.st_mtime, st.st_size, hashlib.md5(open(p, "rb").read()).hexdigest())
    return out
before = digest(ROOT)
opened, net = [], []
def hook(ev, args):
    if ev == "open" and args and isinstance(args[0], (str, bytes)): opened.append((str(args[0]), str(args[1]) if len(args) > 1 else ""))
    elif ev.startswith("socket.") or ev in ("urllib.Request", "http.client.connect"): net.append(ev)
    elif ev == "sqlite3.connect": opened.append((str(args[0]), "sqlite"))
sys.addaudithook(hook)
rc = bw.main(["--home", H, "--home-alias", "C:\\Users\\xiaoming", "--localappdata", f"{H}/AppData/Local", "--appdata", f"{H}/AppData/Roaming",
              "--roots", f"{ROOT}/E", "--out", OUT, "--now", "2026-10-09T10:00:00+08:00", "--tz", "+08:00", "--days", "90", "--with-content"])
check(rc == 0, "main() 返回 0")
opened_by_backfill = list(opened)
after = digest(ROOT)
check(before == after, f"用户目录里 {len(before)} 个文件一个字节都没变（只读）")
bad = [p for p, _ in opened_by_backfill if os.path.basename(p).lower() in ("login data", "cookies", "web data", "logins.json", "key4.db")]
check(not bad, "没碰 Cookies / Login Data / Web Data / logins.json")
writes = [p for p, mode in opened_by_backfill if any(c in mode for c in "wax+") and not os.path.normpath(p).startswith(os.path.normpath(OUT))]
check(not writes, f"所有写入都在输出目录里（越界写入：{writes[:3]}）")
check(not net, "没有任何网络调用")
check(not os.path.exists(os.path.join(OUT, "_tmp")), "临时数据库副本已删除")

evs = [json.loads(l) for l in open(os.path.join(OUT, "events.jsonl"), encoding="utf-8")]
meta = json.load(open(os.path.join(OUT, "meta.json"), encoding="utf-8"))
ts = [datetime.fromisoformat(e["ts"]) for e in evs]
check(ts == sorted(ts), f"{len(evs)} 条事件按时间排好序")
check(all({"ts", "type", "source"} <= e.keys() for e in evs), "每条都有 ts/type/source")
check(all(e["type"] in ("focus", "file_open", "file_save", "file_create") for e in evs), "只有 4 种事件类型")
check(all("dur_s" in e and "app" in e for e in evs if e["type"] == "focus"), "focus 事件都有 app 和 dur_s（检测器需要）")
srcs = {e["source"] for e in evs}
for s in ("backfill:chrome", "backfill:edge", "backfill:tabbit", "backfill:firefox", "backfill:chrome-downloads", "backfill:firefox-downloads", "backfill:recent", "backfill:fs"):
    check(s in srcs, f"有来源 {s}")
urls = [e.get("url", "") for e in evs] + [e.get("source_url", "") or "" for e in evs]
check(not any("SECRET999" in u or "abc123" in u for u in urls), "token 参数值被抹掉")
check(not any(u.startswith("chrome://") for u in urls), "chrome:// 内部页丢弃")
check(not any("t.cn/abc" in u for u in urls) and any("news.example.com" in u for u in urls), "重定向链只留终点")
check(not any("ads.example.com" in u for u in urls), "子框架丢弃")
paths = {e.get("path") for e in evs if e.get("path")}
check(not any("node_modules" in p or "/.git/" in p or "OpenLookout" in p for p in paths), "跳过 node_modules / .git / 输出目录")
check(not any(p.endswith(".jpg") for p in paths) and not any("2025年总结" in p for p in paths), "只要文档类、只要 90 天内")
check("xiaoming/Documents/课题组/实验记录.xlsx" in paths, "Recent .lnk（Unicode）-> 主目录相对路径")
check("xiaoming/Documents/课题组/耗材登记.xlsx" in {e.get("path") for e in evs if e["source"] == "backfill:recent"}, "Recent .lnk（ANSI/GBK）")
check(not any("NAS" in (p or "") for p in paths), "文件夹快捷方式跳过")
check("E:/项目/数据/传感器_0915.csv" not in paths and any(p.startswith("E/项目") or "传感器_0915.csv" in p for p in paths), "--roots 里的文件被扫到")
check(any(e.get("path") == "xiaoming/Downloads/论文模板.pdf" and e["type"] == "file_open" for e in evs), "浏览器里打开的本地 PDF -> file_open")
dl = [e for e in evs if e["source"] == "backfill:chrome-downloads"]
check(len(dl) == 15 and all(e["path"].startswith("xiaoming/Downloads/") and e.get("source_url") for e in dl), "Chrome 下载 15 条，都带来源网址")
man = json.load(open(os.path.join(OUT, "content_manifest.json"), encoding="utf-8"))
check(man and all(os.path.exists(os.path.join(OUT, x["stored"])) for x in man), f"--with-content 复制了 {len(man)} 个文件")
check(meta["mode"] == "backfill" and meta["user_home"] == "xiaoming", "meta.json")
print(json.dumps(meta["source"]["by_source"], ensure_ascii=False))
# 第 9 轮：应用内嵌 WebView / 自动化浏览器不再混成一个 "default" 来源
L, R = "C:/Users/u/AppData/Local", "C:/Users/u/AppData/Roaming"
check(bw.browser_label(L + "/Steam/htmlcache/Default", L) == "appshell-steam", "Steam htmlcache -> appshell-steam")
check(bw.browser_label(L + "/ms-playwright-mcp/mcp-chrome-1/Default", L).startswith("automation-"), "playwright -> automation-*")
check(bw.browser_label(R + "/BurpSuite/pre-wired-browser/Default", R).startswith("automation-"), "Burp 内置浏览器 -> automation-*")
check(bw.browser_label(R + "/SomeApp/EBWebView/Default", R) == "appshell-someapp", "EBWebView -> appshell-*")
check(bw.browser_label(L + "/Microsoft/Edge/User Data", L) == "edge", "Edge 仍然是 edge")
check(bw.browser_label(L + "/Tabbit Browser/User Data", L) == "tabbit", "Tabbit 仍然是 tabbit")
print("FAILED:" if fails else "ALL PASSED", fails)
sys.exit(1 if fails else 0)
