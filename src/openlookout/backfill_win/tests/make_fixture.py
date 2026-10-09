"""在 Linux 上造一个“像 Windows 的”假用户目录，用来测试 backfill_win.py。数据全部是编的。
布局：<root>/C/Users/xiaoming/{AppData/Local, AppData/Roaming, Documents, Desktop, Downloads}，<root>/E/项目
运行：python3 make_fixture.py /tmp/bf_fx"""
import os, sqlite3, struct, sys, shutil
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8)); UTC = timezone.utc
EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
def wk(dt): return int((dt - EPOCH).total_seconds() * 1e6)
def ft(dt): return int((dt - EPOCH).total_seconds() * 1e7)
def T(s): return datetime.fromisoformat(s).replace(tzinfo=TZ)
WIN_HOME = "C:\\Users\\xiaoming"

def chromium_db(path, visits, downloads=()):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path): os.remove(path)
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE urls(id INTEGER PRIMARY KEY, url LONGVARCHAR, title LONGVARCHAR, visit_count INTEGER DEFAULT 0,
        typed_count INTEGER DEFAULT 0, last_visit_time INTEGER, hidden INTEGER DEFAULT 0);
      CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER, from_visit INTEGER, transition INTEGER DEFAULT 0,
        segment_id INTEGER, visit_duration INTEGER DEFAULT 0, incremented_omnibox_typed_score BOOLEAN DEFAULT FALSE);
      CREATE TABLE downloads(id INTEGER PRIMARY KEY, guid VARCHAR, current_path LONGVARCHAR, target_path LONGVARCHAR, start_time INTEGER,
        received_bytes INTEGER, total_bytes INTEGER, state INTEGER, danger_type INTEGER, interrupt_reason INTEGER, hash BLOB,
        end_time INTEGER, opened INTEGER, last_access_time INTEGER, transient INTEGER, referrer VARCHAR, site_url VARCHAR,
        tab_url VARCHAR, tab_referrer_url VARCHAR, http_method VARCHAR, by_ext_id VARCHAR, by_ext_name VARCHAR, etag VARCHAR,
        last_modified VARCHAR, mime_type VARCHAR, original_mime_type VARCHAR);
      CREATE TABLE downloads_url_chains(id INTEGER, chain_index INTEGER, url LONGVARCHAR, PRIMARY KEY(id, chain_index));""")
    ids = {}
    for i, (t, url, title, tr, dur, frm) in enumerate(visits, 1):
        if url not in ids:
            ids[url] = len(ids) + 1; c.execute("INSERT INTO urls(id,url,title) VALUES(?,?,?)", (ids[url], url, title))
        c.execute("INSERT INTO visits(id,url,visit_time,from_visit,transition,visit_duration) VALUES(?,?,?,?,?,?)",
                  (i, ids[url], wk(t), frm, tr, int(dur * 1e6)))
    for i, (t, target, tab_url, file_url, size) in enumerate(downloads, 1):
        c.execute("INSERT INTO downloads(id,guid,current_path,target_path,start_time,end_time,received_bytes,total_bytes,state,tab_url,referrer,mime_type) "
                  "VALUES(?,?,?,?,?,?,?,?,1,?,?,?)", (i, f"g{i}", target, target, wk(t - timedelta(seconds=3)), wk(t), size, size, tab_url, tab_url,
                                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        c.execute("INSERT INTO downloads_url_chains VALUES(?,?,?)", (i, 0, file_url))
    c.commit(); c.close()

def lnk_bytes(target, opened, wtime, size, unicode=True, is_dir=False):
    """按 [MS-SHLLINK] 写一个只有 LinkInfo 的快捷方式。"""
    flags = 0x2 | 0x80
    hdr = struct.pack("<I16sII", 0x4C, bytes.fromhex("0114020000000000c000000000000046"), flags, 0x10 if is_dir else 0x20)
    hdr += struct.pack("<QQQIiIHHII", ft(opened), ft(opened), ft(wtime), size, 0, 1, 0, 0, 0, 0)
    assert len(hdr) == 0x4C
    vol = struct.pack("<IIII", 17, 3, 0x1234, 0x10) + b"\x00"
    if unicode:
        hsize = 0x24; ansi = b"\x00"; suffix_a = b"\x00"
        uni = target.encode("utf-16-le") + b"\x00\x00"; suf_u = b"\x00\x00"
        vol_off = hsize; lbp = vol_off + len(vol); cps = lbp + len(ansi); lbp_u = cps + len(suffix_a); cps_u = lbp_u + len(uni)
        body = vol + ansi + suffix_a + uni + suf_u
        total = hsize + len(body)
        li = struct.pack("<9I", total, hsize, 1, vol_off, lbp, 0, cps, lbp_u, cps_u) + body
    else:
        hsize = 0x1C; ansi = target.encode("gbk") + b"\x00"; suffix_a = b"\x00"
        vol_off = hsize; lbp = vol_off + len(vol); cps = lbp + len(ansi)
        body = vol + ansi + suffix_a; total = hsize + len(body)
        li = struct.pack("<7I", total, hsize, 1, vol_off, lbp, 0, cps) + body
    return hdr + li + b"\x00\x00\x00\x00"

def touch(path, mtime, size=2048):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f: f.write(b"x" * size)
    os.utime(path, (mtime.timestamp(), mtime.timestamp()))

def main(root):
    if os.path.exists(root): shutil.rmtree(root)
    home = os.path.join(root, "C", "Users", "xiaoming"); E = os.path.join(root, "E")
    LA, RA = os.path.join(home, "AppData", "Local"), os.path.join(home, "AppData", "Roaming")
    docs, desk, dl = (os.path.join(home, x) for x in ("Documents", "Desktop", "Downloads"))
    W = lambda *p: WIN_HOME + "\\" + "\\".join(p)

    fridays = [T("2026-07-17T17:20:00") + timedelta(days=7 * i) for i in range(12)]   # 07-17 … 10-02
    # ---- 文件：每周五的周报
    for i, d in enumerate(fridays):
        touch(os.path.join(docs, "周报", f"周报_{d:%Y-%m-%d}.xlsx"), d + timedelta(minutes=i % 3 * 7), 9000 + i)
    # ---- 一份论文的多个版本：叫 final 的不是最新的
    vers = [("开题报告_v1.docx", "2026-08-20T15:00"), ("开题报告_v2.docx", "2026-08-27T21:30"), ("开题报告_final.docx", "2026-09-03T22:10"),
            ("开题报告_最终版.docx", "2026-09-04T23:50"), ("开题报告_v3.docx", "2026-09-05T23:40")]
    for n, t in vers: touch(os.path.join(docs, "论文", n), T(t + ":00"), 50000)
    touch(os.path.join(docs, "论文", "中期考核表.docx"), T("2026-09-26T23:10:00"))
    # ---- 杂项、太旧的文件、要跳过的目录
    touch(os.path.join(desk, "新建 Microsoft Excel 工作表.xlsx"), T("2026-09-10T10:00:00"))
    touch(os.path.join(docs, "旧资料", "2025年总结.docx"), T("2025-12-01T10:00:00"))
    touch(os.path.join(docs, "照片.jpg"), T("2026-09-10T10:00:00"))
    for n, t in (("实验记录.xlsx", "2026-10-02T16:40"), ("耗材登记.xlsx", "2026-10-02T16:55")):
        touch(os.path.join(docs, "课题组", n), T(t + ":00"))
    touch(os.path.join(E, "项目", "数据", "传感器_0901.csv"), T("2026-09-01T09:00:00"))
    touch(os.path.join(E, "项目", "数据", "传感器_0915.csv"), T("2026-09-15T09:00:00"))
    touch(os.path.join(E, "项目", "node_modules", "pkg", "readme.md"), T("2026-09-15T09:00:00"))
    touch(os.path.join(E, "项目", ".git", "notes.txt"), T("2026-09-15T09:00:00"))
    touch(os.path.join(E, "OpenLookout", "data", "old.csv"), T("2026-09-15T09:00:00"))
    # ---- 下载：报销单模板下了 4 次；值班表每周一下一次
    downloads = []
    for i, t in enumerate(["2026-07-24T16:05", "2026-08-21T16:02", "2026-09-11T15:58", "2026-09-25T16:10"]):
        n = "报销单模板.xlsx" if i == 0 else f"报销单模板 ({i}).xlsx"
        touch(os.path.join(dl, n), T(t + ":00"), 31744)
        downloads.append((T(t + ":00"), W("Downloads", n), "https://oa.example.edu.cn/finance/forms", "https://oa.example.edu.cn/files/baoxiao_template.xlsx", 31744))
    for i in range(11):
        t = T("2026-07-20T09:12:00") + timedelta(days=7 * i); n = f"实验室值班表_第{i + 3}周.xlsx"
        touch(os.path.join(dl, n), t, 12000)
        downloads.append((t, W("Downloads", n), "https://lab.example.edu.cn/duty", f"https://lab.example.edu.cn/duty/export?week={i+3}&token=abc123", 12000))

    # ---- Chrome 访问
    v = []
    for d in fridays:
        v.append((d - timedelta(minutes=50), "https://oa.example.edu.cn/weekly/new?token=SECRET999", "周报填报 - 研究所OA", 1, 600, 0))
        v.append((d + timedelta(minutes=12), "https://oa.example.edu.cn/weekly/new?token=SECRET999", "周报填报 - 研究所OA", 7, 20, 0))
    day = T("2026-07-11T12:30:00")
    while day < T("2026-10-09T09:00:00"):
        v.append((day, "https://www.bilibili.com/", "哔哩哔哩", 1, 1800, 0)); day += timedelta(days=1)
    for k, d in enumerate(["2026-07-30T10:00", "2026-08-13T10:05", "2026-08-28T14:00", "2026-09-17T11:00", "2026-10-01T15:30"]):
        v.append((T(d + ":00"), "https://www.baidu.com/s?wd=excel+合并多个工作表", "excel 合并多个工作表_百度搜索", 1, 70, 0))
    v.append((T("2026-09-20T10:00:00"), "chrome://newtab/", "新标签页", 1, 1, 0))
    n0 = len(v)
    v.append((T("2026-09-21T10:00:00"), "https://t.cn/abc", "", 1, 0, 0))                         # 短链（被重定向，应丢弃）
    v.append((T("2026-09-21T10:00:01"), "https://news.example.com/a", "一篇新闻", 0x40000000, 30, n0 + 1))
    v.append((T("2026-09-21T10:00:02"), "https://ads.example.com/frame", "广告框", 3, 0, 0))     # 子框架（应丢弃）
    v.append((T("2026-09-22T09:00:00"), f"file:///C:/Users/xiaoming/Downloads/{'论文模板'}.pdf", "论文模板.pdf", 1, 300, 0))
    chromium_db(os.path.join(LA, "Google", "Chrome", "User Data", "Default", "History"), v, downloads)
    for secret in ("Login Data", "Cookies", "Web Data"):
        with open(os.path.join(LA, "Google", "Chrome", "User Data", "Default", secret), "wb") as f: f.write(b"SECRET-DO-NOT-READ")
    with open(os.path.join(LA, "Google", "Chrome", "User Data", "Local State"), "w") as f: f.write("{}")
    # ---- Edge：研究生院系统，两次在最后一刻提交
    ev = [(T("2026-09-05T23:58:00"), "https://yjs.example.edu.cn/submit", "材料提交 - 研究生院", 7, 40, 0),
          (T("2026-09-26T23:30:00"), "https://yjs.example.edu.cn/submit", "材料提交 - 研究生院", 7, 40, 0),
          (T("2026-08-10T10:00:00"), "https://yjs.example.edu.cn/notice", "通知公告 - 研究生院", 1, 120, 0)]
    chromium_db(os.path.join(LA, "Microsoft", "Edge", "User Data", "Profile 1", "History"), ev)
    # ---- Tabbit（国内版目录名带空格）：每周二看学院周会安排
    tv = [(T("2026-07-14T08:40:00") + timedelta(days=7 * i), "https://chem.example.edu.cn/meeting/week", "本周组会安排 - 化学院", 1, 200, 0) for i in range(12)]
    chromium_db(os.path.join(LA, "Tabbit Browser", "User Data", "Default", "History"), tv)
    # ---- Firefox
    ffd = os.path.join(RA, "Mozilla", "Firefox", "Profiles", "abcd.default-release"); os.makedirs(ffd)
    c = sqlite3.connect(os.path.join(ffd, "places.sqlite"))
    c.executescript("CREATE TABLE moz_places(id INTEGER PRIMARY KEY, url TEXT, title TEXT); CREATE TABLE moz_historyvisits(id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER, visit_type INTEGER);"
                    "CREATE TABLE moz_anno_attributes(id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE moz_annos(id INTEGER PRIMARY KEY, place_id INTEGER, anno_attribute_id INTEGER, content TEXT, dateAdded INTEGER);")
    c.execute("INSERT INTO moz_places VALUES(1,'https://mirrors.example.org/iso','镜像站')")
    c.execute("INSERT INTO moz_historyvisits VALUES(1,1,?,1)", (int(T("2026-09-02T10:00:00").timestamp() * 1e6),))
    c.execute("INSERT INTO moz_anno_attributes VALUES(1,'downloads/destinationFileURI')")
    c.execute("INSERT INTO moz_annos VALUES(1,1,1,'file:///C:/Users/xiaoming/Downloads/%E6%89%8B%E5%86%8C.pdf',?)", (int(T("2026-09-02T10:01:00").timestamp() * 1e6),))
    c.commit(); c.close()
    with open(os.path.join(ffd, "logins.json"), "w") as f: f.write("SECRET")
    # ---- 最近使用 .lnk
    rec = os.path.join(RA, "Microsoft", "Windows", "Recent"); os.makedirs(rec)
    def lnk(name, target, opened, wtime, **kw):
        p = os.path.join(rec, name)
        with open(p, "wb") as f: f.write(lnk_bytes(target, opened, wtime, 9000, **kw))
        os.utime(p, (opened.timestamp(), opened.timestamp()))
    lnk("实验记录.xlsx.lnk", W("Documents", "课题组", "实验记录.xlsx"), T("2026-10-02T16:30:00"), T("2026-10-02T16:40:00"))
    lnk("耗材登记.xlsx.lnk", W("Documents", "课题组", "耗材登记.xlsx"), T("2026-10-02T16:45:00"), T("2026-10-02T16:55:00"), unicode=False)
    lnk("周报_2026-10-02.xlsx.lnk", W("Documents", "周报", "周报_2026-10-02.xlsx"), T("2026-10-02T17:10:00"), T("2026-10-02T17:34:00"))
    lnk("开题报告_v3.docx.lnk", W("Documents", "论文", "开题报告_v3.docx"), T("2026-09-05T22:00:00"), T("2026-09-05T23:40:00"))
    lnk("网盘资料.lnk", "\\\\NAS\\share\\资料", T("2026-09-05T22:00:00"), T("2026-09-05T22:00:00"), is_dir=True)
    with open(os.path.join(rec, "坏掉的.docx.lnk"), "wb") as f: f.write(b"not a link")
    print("fixture at", root)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bf_fx")
