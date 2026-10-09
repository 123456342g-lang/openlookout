"""历史回溯模式（backfill）的检测器与求解器。输入是 backfill_win 生成的 events.jsonl：
没有剪贴板、没有窗口焦点，只有网页访问（页面加载）、下载、最近打开、文件创建/最后修改时间。
所以这里按“天/周”这种粗粒度找节律，而不是按分钟找会话。纯规则，不用模型。"""
import csv, json, re, shutil, statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

WD = "一二三四五六日"
# 刷着玩/通用工具网站：每周去几次也不算“例行公事”
NOISE_HOSTS = re.compile(r"(^|\.)(baidu|google|bing|sogou|so|bilibili|youtube|douyin|tiktok|weibo|zhihu|xiaohongshu|taobao|jd|tmall|"
                         r"qq|163|126|github|stackoverflow|csdn|iqiyi|youku|netflix|twitter|x|facebook|chatgpt|openai|deepseek|kimi|doubao)\.(com|cn|net|org|ai)$")
VERSION_TOKEN = re.compile(r"(?:[\s_\-—.]*(?:final|最终版?|终稿|终版|定稿|修改稿?|修订版?|修改版|改|新版?|最新版?|copy|副本|v\d+(?:\.\d+)?|ver\d+|"
                           r"版本\d+|第\d+版|r\d+|\d版))+$", re.I)
FINAL_TOKEN = re.compile(r"final|最终|终稿|终版|定稿", re.I)
DL_DUP = re.compile(r"\s*[\(（]\d+[\)）]$|\s*-\s*副本$|\s*-\s*copy$", re.I)
DATEISH = re.compile(r"\d")

# ------------------------------------------------------------- 噪声来源：不是这个人在用浏览器
# backfill_win 新版把自动化浏览器标成 automation-*、应用内嵌 WebView（Steam、代理客户端、桌面 App）标成 appshell-*；
# 旧版输出里它们全都叫 "default"（profile 目录名），分不出是谁，只能整体丢掉。
APP_HOSTS = re.compile(r"^(localhost|127(\.\d+){3}|0\.0\.0\.0|\[?::1\]?|[\w.-]+\.localhost|steamloopback\.host)$")
def filter_noise(evs):
    keep, dropped = [], Counter()
    for e in evs:
        src = str(e.get("source", "")); lab = src.split(":", 1)[1] if ":" in src else ""
        base = lab[:-len("-downloads")] if lab.endswith("-downloads") else lab
        if base.startswith(("automation-", "appshell-")) or base == "default":
            dropped["自动化/应用外壳浏览器（" + (base.split("-", 1)[0] if base != "default" else "旧版未区分的 default") + "）"] += 1; continue
        if e["type"] == "focus" and e.get("url"):
            sp = urlsplit(e["url"]); host = (sp.hostname or "").lower()
            if sp.scheme not in ("http", "https"): dropped["浏览器内部页/本地文件页"] += 1; continue
            if APP_HOSTS.match(host): dropped["本机开发/应用页面（localhost 等）"] += 1; continue
        keep.append(e)
    return keep, dict(dropped)

def _p(path): return PurePosixPath(path)
def pretty_pattern(name):
    """周报_2026-10-02.xlsx -> 周报_〈日期〉.xlsx；值班表_第13周.xlsx -> 值班表_第〈N〉周.xlsx"""
    s = re.sub(r"20\d\d[-_.]?\d{1,2}[-_.]?\d{1,2}", "〈日期〉", name)
    return re.sub(r"\d+", "〈N〉", s)
def _hist(evs): return [e for e in evs if str(e.get("source", "")).startswith("backfill:")]

def _rhythm(dates):
    """一组日期 → (周期天数, 是否规律, 最常见的星期几, 星期集中度)"""
    days = sorted(set(dates))
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    if not gaps: return None, False, None, 0
    med = statistics.median(gaps)
    near = sum(1 for g in gaps if abs(g - med) <= max(1, med * 0.2)) / len(gaps)
    wd, n = Counter(d.weekday() for d in days).most_common(1)[0]
    return med, (near >= 0.7 and med >= 5), wd, n / len(days)

# ------------------------------------------------------------- 1. 每周固定去同一个网页（尤其是要提交表单的）
def detect_site_rhythm(evs, meta):
    by = defaultdict(list)
    for e in _hist(evs):
        if e["type"] != "focus" or not e.get("url"): continue
        if e.get("transition") in ("toplevel", "generated", "auto_toplevel"): continue   # 浏览器/别的程序自动打开的（比如更新后弹出的“更新日志”），不是人要去的
        sp = urlsplit(e["url"])
        host = (sp.hostname or "").lower()
        if not host or NOISE_HOSTS.search(host) or sp.scheme not in ("http", "https"): continue
        key = host + re.sub(r"\d+", "#", sp.path.rstrip("/"))
        by[key].append(e)
    out = []
    now = meta["now_dt"]
    for key, lst in by.items():
        dates = [e["dt"].date() for e in lst]
        days = sorted(set(dates)); weeks = {d.isocalendar()[:2] for d in days}
        if len(weeks) < 3 or len(days) / len(weeks) > 2.5: continue        # 太少，或者几乎天天去（日常习惯，不是例行公事）
        period, regular, wd, conc = _rhythm(dates)
        if not (regular or conc >= 0.6): continue
        submits = [e for e in lst if e.get("transition") == "form_submit"]
        hours = [e["dt"].hour + e["dt"].minute / 60 for e in lst]
        nxt = days[-1] + timedelta(days=round(period or 7))
        title = Counter(e.get("title") or "" for e in lst).most_common(1)[0][0]
        score = 10 + len(weeks) * 2 + len({e["dt"].date() for e in submits}) * 4
        out.append({"kind": "site_rhythm", "score": score,
            "local": {"key": key, "url": lst[-1]["url"], "title": title, "app": lst[-1]["app"], "dates": [str(d) for d in days],
                      "submit_dates": sorted({str(e["dt"].date()) for e in submits}), "usual_hour": round(statistics.median(hours), 1),
                      "next_due": str(nxt), "weekday": wd},
            "facts": {"weeks": len(weeks), "visit_days": len(days), "period_days": period, "weekday": "周" + WD[wd],
                      "weekday_share": round(conc, 2), "form_submits": len({e["dt"].date() for e in submits}),
                      "usual_time": f"{int(statistics.median(hours)):02d}:00 前后", "due_today_or_overdue": nxt <= now.date()}})
    return out

# ------------------------------------------------------------- 2. 同一个文件反复下载
def detect_repeated_download(evs, meta):
    by = defaultdict(list)
    for e in _hist(evs):
        if e["type"] != "file_create" or "downloads" not in e.get("source", ""): continue
        p = _p(e["path"]); stem = DL_DUP.sub("", p.stem)
        by[(stem.lower(), p.suffix.lower())].append(e)
    out = []
    for (stem, ext), lst in by.items():
        days = sorted({e["dt"].date() for e in lst})
        if len(lst) < 3 and not (len(lst) >= 2 and len(days) >= 2): continue
        sizes = Counter(e.get("size") for e in lst)
        same_size = sizes.most_common(1)[0][1]
        srcs = Counter(urlsplit(e.get("file_url") or e.get("source_url") or "").path for e in lst)
        out.append({"kind": "repeated_download", "score": 6 + len(lst) * 3 + (same_size - 1) * 2,
            "local": {"name": _p(lst[0]["path"]).name, "copies": [{"path": e["path"], "ts": e["ts"], "size": e.get("size"), "from": e.get("source_url")} for e in lst],
                      "all_gone": all(e.get("exists_now") is False for e in lst),
                      "days": [str(d) for d in days]},
            "facts": {"times": len(lst), "days": len(days), "same_size_copies": same_size, "same_source": srcs.most_common(1)[0][1] == len(lst),
                      "total_kb": round(sum(e.get("size") or 0 for e in lst) / 1024), "file_type": ext.lstrip(".")}})
    return out

# ------------------------------------------------------------- 3. 按周/按月出一份的“带日期/编号”的文件
def _file_times(evs):
    first, last = {}, {}
    for e in _hist(evs):
        if e["type"] in ("file_create", "file_save") and e.get("path"):
            p = e["path"]; first[p] = min(first.get(p, e["dt"]), e["dt"]); last[p] = max(last.get(p, e["dt"]), e["dt"])
    return first, last

def detect_recurring_files(evs, meta):
    first, last = _file_times(evs)
    groups = defaultdict(list)
    for p, t in first.items():
        pp = _p(p)
        core = VERSION_TOKEN.sub("", DL_DUP.sub("", pp.stem))      # “(1)”“_v3”这类不算日期/编号
        if not DATEISH.search(core): continue
        groups[(str(pp.parent), re.sub(r"\d+", "#", pp.name))].append((t, p))
    out = []
    now = meta["now_dt"]
    for (folder, pattern), occ in groups.items():
        if len(occ) < 3: continue
        occ.sort()
        period, regular, wd, conc = _rhythm([t.date() for t, _ in occ])
        if not regular: continue
        downloaded = sum(1 for e in evs if e["type"] == "file_create" and "downloads" in e.get("source", "") and e["path"] in {p for _, p in occ})
        nxt = occ[-1][0] + timedelta(days=round(period))
        hours = [t.hour + t.minute / 60 for t, _ in occ]
        out.append({"kind": "recurring_files", "score": 18 + len(occ) * 2 + (15 if nxt.date() <= now.date() else 0) - (10 if downloaded else 0),
            "local": {"folder": folder, "pattern": pattern, "pretty": pretty_pattern(occ[-1][1].rsplit("/", 1)[-1]), "files": [p for _, p in occ], "dates": [t.strftime("%Y-%m-%d %H:%M") for t, _ in occ],
                      "last": occ[-1][1], "next_due": nxt.strftime("%Y-%m-%d"), "weekday": wd, "usual_hour": statistics.median(hours),
                      "downloaded": bool(downloaded)},
            "facts": {"occurrences": len(occ), "period_days": period, "weekday": "周" + WD[wd], "usual_time": f"{int(statistics.median(hours)):02d}:00 前后",
                      "made_by": "从网上下载" if downloaded else "自己新建/编辑", "due_today_or_overdue": nxt.date() <= now.date(),
                      "next_due_in_days": (nxt.date() - now.date()).days}})
    return out

# ------------------------------------------------------------- 4. 同一份文件的一堆版本（final 不一定是最新的）
def detect_version_sprawl(evs, meta):
    first, last = _file_times(evs)
    fam = defaultdict(list)
    for p in last:
        pp = _p(p); base = VERSION_TOKEN.sub("", pp.stem).strip(" _-—")
        if len(base) < 2: continue
        extfam = {".docx": ".doc", ".wps": ".doc", ".xlsx": ".xls", ".et": ".xls", ".pptx": ".ppt", ".dps": ".ppt"}.get(pp.suffix.lower(), pp.suffix.lower())
        fam[(base.lower(), extfam)].append(p)
    out = []
    for (base, ext), ps in fam.items():
        tagged = [p for p in ps if VERSION_TOKEN.search(_p(p).stem)]
        if len(ps) < 3 or len(tagged) < 2: continue
        ps.sort(key=lambda p: last[p])
        newest = ps[-1]
        finals = [p for p in ps if FINAL_TOKEN.search(_p(p).stem)]
        stale_finals = [p for p in finals if (last[newest] - last[p]).total_seconds() > 3600]
        saves = sorted(last[p] for p in ps)
        burst = max((sum(1 for t in saves if a <= t <= a + timedelta(hours=48)) for a in saves), default=0)
        late = sum(1 for t in saves if t.hour >= 22 or t.hour < 4)
        out.append({"kind": "version_sprawl", "score": 10 + len(ps) * 3 + (25 if stale_finals else 0) + (5 if burst >= 3 else 0),
            "local": {"base": base, "files": [{"path": p, "saved": last[p].strftime("%Y-%m-%d %H:%M")} for p in ps], "newest": newest,
                      "stale_finals": stale_finals, "folders": sorted({str(_p(p).parent) for p in ps})},
            "facts": {"versions": len(ps), "folders": len({str(_p(p).parent) for p in ps}), "named_final": len(finals),
                      "final_is_not_newest": bool(stale_finals), "span_days": (saves[-1] - saves[0]).days,
                      "max_versions_in_48h": burst, "late_night_saves": late, "file_type": ext.lstrip(".")}})
    return out

# ------------------------------------------------------------- 5. 赶在最后一刻：改完文件几分钟后就去网页上提交
def detect_last_minute(evs, meta):
    hist = _hist(evs)
    saves = sorted((e["dt"], e["path"]) for e in hist if e["type"] == "file_save" and _p(e["path"]).suffix.lower() in (".docx", ".doc", ".xlsx", ".pdf", ".pptx", ".wps", ".et"))
    by = defaultdict(list)
    for e in hist:
        if e["type"] != "focus" or e.get("transition") != "form_submit": continue
        prior = [(t, p) for t, p in saves if e["dt"] - timedelta(hours=3) <= t <= e["dt"]]
        if not prior: continue
        t, p = prior[-1]
        sp = urlsplit(e["url"]); by[(sp.hostname or "") + sp.path].append({"submit": e["dt"], "saved": t, "path": p, "title": e.get("title")})
    out = []
    for key, lst in by.items():
        days = {x["submit"].date() for x in lst}
        late = sum(1 for x in lst if x["submit"].hour >= 22 or x["submit"].hour < 4)
        if len(days) < 2 or late < 2: continue      # 白天改完马上交是正常流程；深夜赶着交才算“最后一刻”
        mins = [round((x["submit"] - x["saved"]).total_seconds() / 60) for x in lst]
        out.append({"kind": "last_minute", "score": 10 + len(days) * 5 + late * 3,
            "local": {"site": key, "title": lst[-1]["title"], "events": [{"saved": x["saved"].strftime("%m-%d %H:%M"), "submitted": x["submit"].strftime("%m-%d %H:%M"),
                                                                          "file": x["path"]} for x in lst]},
            "facts": {"times": len(days), "median_minutes_save_to_submit": statistics.median(mins), "late_night": late}})
    return out

DETECTORS = [detect_site_rhythm, detect_repeated_download, detect_recurring_files, detect_version_sprawl, detect_last_minute]

def run_history(evs, meta):
    fs = []
    for d in DETECTORS: fs += d(evs, meta)
    # 同一批文件既是“周期文件”又是“网页周期”时都保留；“周期文件”里的下载类，交给“重复下载”时去掉重复
    return fs

# ============================================================= 描述（发给云端前，只有统计量，不含网址/文件名/标题）
def describe(f):
    k, F = f["kind"], f["facts"]
    if k == "site_rhythm":
        when = (f"几乎每{F['weekday']}（占 {int(F['weekday_share']*100)}%）{F['usual_time']}" if F["weekday_share"] >= 0.6 else f"大约每 {F['period_days']:g} 天")
        return (f"用户过去 {F['weeks']} 周里，{when}都会打开同一个工作网页，"
                + (f"其中 {F['form_submits']} 次在上面提交了表单" if F["form_submits"] else "但没有提交表单") + ("；按节律今天/已经该去了" if F["due_today_or_overdue"] else "") + "。")
    if k == "repeated_download":
        return (f"同一个 {F['file_type']} 文件被下载了 {F['times']} 次（{F['days']} 个不同的日子），其中 {F['same_size_copies']} 份大小完全一样"
                + ("，都来自同一个下载地址" if F["same_source"] else "") + ("；这些副本现在都已经删掉了。" if f["local"].get("all_gone") else "；下载文件夹里留着多份副本。"))
    if k == "recurring_files":
        return (f"同一个文件夹里有 {F['occurrences']} 份同一命名规则、带日期/编号的文件，大约每 {F['period_days']:g} 天一份，多在{F['weekday']}{F['usual_time']}，"
                f"是{F['made_by']}的；按节律下一份" + (("应该已经发布了" if F["made_by"] == "从网上下载" else "今天就该做了") if F["due_today_or_overdue"] else f"还有 {F['next_due_in_days']} 天") + "。")
    if k == "version_sprawl":
        return (f"同一份 {F['file_type']} 文档存了 {F['versions']} 个版本（分布在 {F['folders']} 个文件夹），其中 {F['named_final']} 个名字里带“最终/final”"
                + ("，但带“最终”的并不是最后改的那个" if F["final_is_not_newest"] else "") + f"；最密集时 48 小时内存了 {F['max_versions_in_48h']} 版，{F['late_night_saves']} 次在深夜。")
    if k == "manual_summary":
        return (f"{F['workbooks']} 个同样格式的工作簿，合计 {F['detail_sheets']} 张按周的明细表；每个工作簿另有一张手工填写、没有公式的汇总表；每个文件在两个文件夹里各存了一份一样的。"
                f"按明细重新加总后，汇总里共有 {F['cells_differ']} 格（涉及 {F['rows_differ']} 人次）和明细合计不一致" + (f"；其中 {F['rows_explained_by_rule']} 人次可以用一条折算规则（{F['rule_desc']}，只在 {F['rule_workbooks']} 个工作簿里成立）解释，剩 {F['rows_unexplained']} 人次 {F['cells_unexplained']} 格解释不了" if F["rule_found"] else "，找不到统一的折算规则") + "。")
    if k == "numbered_series":
        return (f"同一个课程文件夹下有 {F['episodes']} 期编号连续的任务（{F['span_days']} 天内，平均 {F['days_per_episode']:g} 天一期，开始多在{F['weekday']}），共留下 {F['deliverable_files']} 个报告类文件；"
                f"{F['episodes_with_multiple_files']} 期各有 2 个以上报告文件（最多 {F['max_files_one_episode']} 个，{F['identical_size_pairs']} 对大小完全相同），文件名的前缀写法有 {F['naming_styles']} 种；按节奏下一期约在 {F['next_in_days']} 天后。")
    if k == "duplicate_copies":
        return f"有 {F['files']} 个文件以同名同大小出现在 {F['max_folders']} 个不同文件夹里。"
    if k == "last_minute":
        return (f"用户有 {F['times']} 次在网页上提交材料前，最后一次改文件距离提交只有约 {F['median_minutes_save_to_submit']:g} 分钟，其中 {F['late_night']} 次在深夜 22 点以后。")
    return str(F)

KIND_CN = {"site_rhythm": "每周固定要去的网页", "repeated_download": "同一个文件反复下载", "recurring_files": "按周期出一份的文件",
           "version_sprawl": "版本太多分不清", "last_minute": "总在最后一刻提交"}

def evidence(f):
    L, k = f["local"], f["kind"]
    if k == "site_rhythm":
        return [f"「{L['title']}」 {L['url'][:80]}", "去过：" + "、".join(d[5:] for d in L["dates"][-8:])] + (["提交过：" + "、".join(d[5:] for d in L["submit_dates"][-6:])] if L["submit_dates"] else [])
    if k == "repeated_download":
        return [f"{c['ts'][:16].replace('T', ' ')} → {c['path']}（{(c['size'] or 0)//1024} KB）" for c in L["copies"][:6]]
    if k == "recurring_files":
        return [f"{d} {Path(p).name}" for d, p in list(zip(L["dates"], L["files"]))[-6:]] + [f"按节律下一份：{L['next_due']}"]
    if k == "version_sprawl":
        return [f"{x['saved']} {x['path']}" + ("  ← 最新" if x["path"] == L["newest"] else "  ← 叫“最终”但不是最新" if x["path"] in L["stale_finals"] else "") for x in L["files"]]
    if k == "manual_summary":
        ev = []
        for part in L.get("parts") or [L]:
            A = part["analysis"]; R = A["rule"]; left = {(a, b) for a, b, *_ in (R["left"] if R else A["raw_diffs"])}
            ev.append(f"{Path(part['file']).name}（{len(part['copies'])} 份相同副本，最后修改 {part['last_saved'] or '?'}）：明细 {len(A['details'])} 张，汇总表没有公式，"
                      f"{len(A['raw_diffs'])} 格对不上" + (f"；每 {R['k']} 次{R['from']}折 1 节{R['to']} 解释了 {R['rows_explained']}/{R['rows_with_diff']} 人" if R else ""))
            ev += [f"  需核对：第{i}处 {b} 明细合计 {cv:g}，汇总填 {hv:g}" for i, (a, b, cv, hv) in enumerate([x for x in A["raw_diffs"] if (x[0], x[1]) in left][:6], 1)]
        return ev
    if k == "numbered_series":
        ev = [f"{L['root']}/{L['prefix']}{n} 开始于 {L['starts'][n] if n in L['starts'] else L['starts'][str(n)]}，报告类文件 {len(L['items'].get(n) or L['items'].get(str(n)) or [])} 个" for n in L["numbers"]]
        return ev + [f"文件名前缀写法：{'、'.join(L['styles'])}", f"按节奏下一期：{L['prefix']}{L['next_n']}，约 {L['next_date']}"]
    if k == "duplicate_copies":
        return [f"{g['name']}（{g['size']//1024} KB）× {len(g['folders'])} 处" for g in L["groups"][:8]]
    if k == "last_minute":
        return [f"{x['saved']} 改完 {Path(x['file']).name} → {x['submitted']} 提交" for x in L["events"]]
    return []

# ============================================================= 求解（确定性，只生成新文件，不改、不删用户的任何东西）
def _ics(path, title, first_dt, period_days, minutes_before=60, desc=""):
    start = first_dt - timedelta(minutes=minutes_before)
    freq = "WEEKLY" if round(period_days) % 7 == 0 else "DAILY"
    interval = max(1, round(period_days) // 7) if freq == "WEEKLY" else max(1, round(period_days))
    txt = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OpenLookout//backfill//CN", "BEGIN:VEVENT",
                       f"UID:{abs(hash((title, start.isoformat())))}@openlookout", f"DTSTAMP:{datetime.now():%Y%m%dT%H%M%S}",
                       f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DURATION:PT30M", f"RRULE:FREQ={freq};INTERVAL={interval}",
                       f"SUMMARY:{title}", f"DESCRIPTION:{desc}", "END:VEVENT", "END:VCALENDAR", ""])
    Path(path).write_text(txt, encoding="utf-8"); return str(path)

def _next_name(name, period_days):
    """把文件名里的日期按周期往后推一份：周报_2026-10-02.xlsx -> 周报_2026-10-09.xlsx；第12周 -> 第13周"""
    m = re.search(r"(20\d\d)[-_.]?(\d\d)[-_.]?(\d\d)", name)
    if m:
        d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) + timedelta(days=round(period_days))
        sep = name[m.start(1) + 4:m.start(2)]
        return name[:m.start()] + f"{d:%Y}{sep}{d:%m}{sep}{d:%d}" + name[m.end():]
    m = list(re.finditer(r"\d+", name))
    if m:
        x = m[-1]; return name[:x.start()] + str(int(x.group()) + 1).zfill(len(x.group())) + name[x.end():]
    return None

def solve(f, env):
    k, L, F = f["kind"], f["local"], f["facts"]
    d = Path(env.run_dir) / "work" / f["id"]; d.mkdir(parents=True, exist_ok=True)
    tree = getattr(env, "tree", None)
    real = lambda rel: (tree / rel) if tree and (tree / rel).exists() else None
    if k == "version_sprawl":
        p = d / "版本清单.csv"
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh); w.writerow(["文件", "所在文件夹", "最后修改", "标记"])
            for x in reversed(L["files"]):
                w.writerow([Path(x["path"]).name, str(Path(x["path"]).parent), x["saved"],
                            "最新（按修改时间）" if x["path"] == L["newest"] else ("名字叫“最终”，但不是最新" if x["path"] in L["stale_finals"] else "")])
        ok = all(x["saved"] <= next(y["saved"] for y in L["files"] if y["path"] == L["newest"]) for x in L["files"])
        return {"status": "verified" if ok else "draft", "artifacts": [str(p)],
                "slots": {"文档": L["base"], "版本数": str(F["versions"]), "最新版本": Path(L["newest"]).name,
                          "叫最终的版本": "、".join(Path(x).name for x in L["stale_finals"]) or "无"},
                "workflow": {"explain": "按修改时间把所有版本排好，标出真正最新的一份；没有删除或移动任何文件"},
                "verify_deid": {"newest_is_max_mtime": ok, "final_is_not_newest": F["final_is_not_newest"], "files_touched": 0}}
    if k == "repeated_download" and L.get("all_gone"):
        return {"status": "omit", "artifacts": [], "slots": {}, "workflow": {"explain": "这些副本现在都已经不在下载文件夹里了，没有要替你清理的东西"},
                "verify_deid": {"mode": "observation_only", "copies_exist_now": 0}}
    if k == "repeated_download":
        p = d / "重复下载清单.csv"
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh); w.writerow(["下载时间", "保存位置", "大小(KB)", "来源网页"])
            for c in L["copies"]: w.writerow([c["ts"][:16].replace("T", " "), c["path"], (c["size"] or 0) // 1024, c["from"] or ""])
        # 有内容副本时，用哈希确认哪些是一模一样的
        import hashlib
        hashes = [hashlib.sha1(real(c["path"]).read_bytes()).hexdigest() if real(c["path"]) else None for c in L["copies"]]
        identical = Counter(h for h in hashes if h).most_common(1)[0][1] if any(hashes) else None
        return {"status": "verified", "artifacts": [str(p)],
                "slots": {"文件": L["name"], "下载次数": str(F["times"]), "完全相同的份数": str(identical or F["same_size_copies"])},
                "workflow": {"explain": "列出每次下载的时间、位置和来源；" + ("按内容哈希确认了完全相同的副本" if identical else "按文件大小判断可能相同（没读内容）")},
                "verify_deid": {"identical_by_hash": identical, "identical_by_size": F["same_size_copies"], "files_touched": 0}}
    if k == "recurring_files":
        last = Path(L["last"]); arts = []
        due = datetime.fromisoformat(L["next_due"]).replace(hour=int(L["usual_hour"]), minute=int(L["usual_hour"] % 1 * 60))
        arts.append(_ics(d / "例行提醒.ics", f"该做：{L['pretty']}", due, F["period_days"], desc="OpenLookout 从你的历史文件里发现的节律"))
        nxt = _next_name(last.name, F["period_days"]); src = real(L["last"]); status = "reminder_only"
        if nxt and src and not L["downloaded"]:
            shutil.copyfile(src, d / nxt); arts.insert(0, str(d / nxt)); status = "verified"
        return {"status": status, "artifacts": arts,
                "slots": {"文件规律": L["pretty"], "份数": str(F["occurrences"]), "下一份": nxt or "", "下次日期": L["next_due"], "星期": F["weekday"]},
                "workflow": {"explain": ("按命名规则把下一份建好了（先复制上一份，等你改）；" if status == "verified" else "") + "做了一个按节律重复的日历提醒（.ics，导入才生效）"},
                "verify_deid": {"next_file_created": status == "verified", "needs_content_for_draft": src is None, "files_touched": 0}}
    if k == "site_rhythm":
        due = datetime.fromisoformat(L["next_due"]).replace(hour=int(L["usual_hour"]), minute=0)
        ics = _ics(d / "例行网页提醒.ics", f"例行：{L['title'][:30]}", due, F["period_days"] or 7, desc=L["url"])
        url = d / "打开这个网页.url"; url.write_text(f"[InternetShortcut]\r\nURL={L['url']}\r\n", encoding="utf-8")
        return {"status": "reminder_only", "artifacts": [ics, str(url)],
                "slots": {"网页": L["title"][:40], "星期": F["weekday"], "周数": str(F["weeks"]), "提交次数": str(F["form_submits"]), "下次日期": L["next_due"]},
                "workflow": {"explain": "做了一个按节律重复的提醒和一键打开的快捷方式；还没有替你填表（需要浏览器扩展记录表单字段后才能做）"},
                "verify_deid": {"form_fields_known": False, "files_touched": 0}}
    if k == "manual_summary":
        from . import sheet_audit as S
        arts, checks, ok = [], [], True
        for part in L.get("parts") or [L]:
            A = part["analysis"]; out = d / (Path(part["file"]).stem.strip() + "_自动汇总与核对.xlsx")
            expect, keys = S.build(A, out)
            V = S.verify(A, out, expect, keys, d / "_recalc")
            ok &= V["cells_checked"] > 0 and V["cells_match"] == V["cells_checked"] and bool(V["original_sheets_unchanged"]) and V["rule_cells_match"] == V["rule_cells_checked"]
            arts.append(str(out)); checks.append(V)
        shutil.rmtree(d / "_recalc", ignore_errors=True)
        R = next((p["analysis"]["rule"] for p in (L.get("parts") or [L]) if p["analysis"]["rule"]), None)
        return {"status": "verified" if ok else "draft", "artifacts": arts,
                "slots": {"文件": "、".join(Path(p["file"]).name.strip() for p in (L.get("parts") or [L])), "工作簿数": str(F["workbooks"]), "明细表数": str(F["detail_sheets"]),
                          "对不上的格数": str(F["cells_differ"]), "对不上的人次": str(F["rows_differ"]), "规则解释的人次": str(F["rows_explained_by_rule"]),
                          "仍需核对的人次": str(F["rows_unexplained"]), "仍需核对的格数": str(F["cells_unexplained"]),
                          "折算规则": (f"每 {R['k']} 次{R['from']}折 1 节{R['to']}" if R else "无"), "副本数": str(F["identical_copies"])},
                "workflow": {"explain": "按每周明细重新加总，每个工作簿生成一份新表：原表不动，加一张用公式自动汇总的表和一张差异核对表" + ("；推测出折算规则的那份另附按规则折算后的版本" if R else "")},
                "verify_deid": {"重算工具": "LibreOffice 无界面重算公式" if not checks[0]["recalc_engine"].startswith("不可用") else checks[0]["recalc_engine"],
                                "公式汇总与逐周相加一致的格数": f"{sum(v['cells_match'] for v in checks)}/{sum(v['cells_checked'] for v in checks)}",
                                "按折算规则的版本一致的格数": f"{sum(v['rule_cells_match'] for v in checks)}/{sum(v['rule_cells_checked'] for v in checks)}",
                                "原有工作表逐格未改动": all(v["original_sheets_unchanged"] for v in checks), "改动用户原文件数": 0}}
    if k == "numbered_series":
        from . import series_kit as K
        B = K.build(f, d); V = K.verify(f, B, d / "_sandbox")
        ok = V["episodes_replayed"] >= 3 and V["title_and_number_match"] == V["episodes_replayed"] and V["dry_run_never_writes"] and V["do_mode_created"] >= 1 and V["rerun_skips_existing"]
        shutil.rmtree(d / "_sandbox", ignore_errors=True)
        (d / "验证记录.json").write_text(json.dumps(V, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"status": "verified" if ok else "draft", "artifacts": [B["index"], B["script"], str(d / "验证记录.json")],
                "slots": {"系列": L["prefix"], "期数": str(F["episodes"]), "交付文件数": str(F["deliverable_files"]), "多文件的期数": str(F["episodes_with_multiple_files"]),
                          "命名写法数": str(F["naming_styles"]), "下一期": f"{L['prefix']}{L['next_n']}", "下一期日期": L["next_date"], "前缀": B["prefix"] or "（无）"},
                "workflow": {"explain": "列出每一期留下的报告文件、标出最新的和大小完全相同的副本；写了一个开新一期的小脚本（默认只演示），按最近一次的命名写法从任务书推出文件名、复制你的报告模板"},
                "verify_deid": {"episodes_replayed": V["episodes_replayed"], "title_and_number_match": V["title_and_number_match"], "dry_run_never_writes": V["dry_run_never_writes"],
                                "do_mode_created": V["do_mode_created"], "rerun_skips_existing": V["rerun_skips_existing"], "files_touched": 0}}
    if k == "duplicate_copies":
        return {"status": "omit", "artifacts": [], "slots": {}, "workflow": {"explain": "多半是有意放两处（同一份材料交两个地方），只记录"}, "verify_deid": {"mode": "observation_only"}}
    if k == "last_minute":
        return {"status": "omit", "artifacts": [], "slots": {"次数": str(F["times"])},
                "workflow": {"explain": "只是一条观察：没有可以替你做好的东西"}, "verify_deid": {"mode": "observation_only"}}
    return {"status": "omit", "artifacts": [], "slots": {}, "workflow": {"explain": ""}, "verify_deid": {}}

# ============================================================= 不调模型时的卡片模板
def template_card(f, r):
    k, F, s = f["kind"], f["facts"], r.get("slots", {})
    q, opts = "以后要不要我每次都这样准备好？", ["以后自动做", "只这一次", "不用"]
    if k == "version_sprawl":
        t = "“最终版”其实不是最新的" if F["final_is_not_newest"] else f"同一份文档有 {F['versions']} 个版本"
        return {"title": t, "noticed": f"{{文档}} 有 {{版本数}} 个版本，名字叫“最终”的 {{叫最终的版本}} 比 {{最新版本}} 更早。" if F["final_is_not_newest"] else f"{{文档}} 存了 {{版本数}} 个版本。",
                "prepared": "按修改时间排好的版本清单，标出了真正最新的一份。", "verified": "按文件修改时间核对过，没有动任何文件。",
                "question": "要不要以后每次发文件前先帮你确认是最新版？", "options": ["要", "不用"]}
    if k == "repeated_download":
        return {"title": f"{s.get('文件')} 下载了 {s.get('下载次数')} 次", "noticed": "同一个文件你已经下载了 {下载次数} 次，下载文件夹里有多份副本。",
                "prepared": "一份重复下载清单，标出了每次的时间、位置和来源网页。", "verified": "{完全相同的份数} 份是一样的（按大小或内容核对）。",
                "question": "要不要把它固定在一个位置，下次直接打开？", "options": ["要", "不用"]}
    if k == "recurring_files":
        if F["made_by"] == "从网上下载":
            return {"title": f"{s.get('文件规律')} 每{F['weekday']}更新", "noticed": "这份表大约每周更新一次，你已经下载了 {份数} 份，按节律 {下次日期} 应该有新的一份。",
                    "prepared": "一个按节律重复的日历提醒。", "verified": "只是提醒：要自动去下载，需要知道下载页面的规律（下一版）。",
                    "question": "要不要以后有新的一份就提醒你？", "options": ["要", "不用"]}
        return {"title": f"每{F['weekday']}一份的 {s.get('文件规律')}", "noticed": "这类文件你已经做了 {份数} 份，节律很稳，下一份是 {下次日期}。",
                "prepared": ("下一份 {下一份} 已经按命名规则建好（复制自上一份），" if r["status"] == "verified" else "") + "还有一个按节律重复的日历提醒。",
                "verified": "命名和日期按过去的规律推出来；内容还是上一份的，需要你改。" if r["status"] == "verified" else "只做了提醒，要真正帮你做内容，需要允许读取这些文件（--with-content）。",
                "question": q, "options": opts}
    if k == "site_rhythm":
        return {"title": f"每{F['weekday']}都要去「{s.get('网页')}」", "noticed": "过去 {周数} 周你几乎每{星期}都打开这个网页" + ("，在上面提交过 {提交次数} 次。" if F["form_submits"] else "。"),
                "prepared": "一个按节律重复的提醒和一键打开的快捷方式。", "verified": "还没有替你填表：需要装浏览器扩展记下表单字段后才能做。",
                "question": "要不要以后每周提前帮你把这页准备好？", "options": ["要", "不用"]}
    if k == "manual_summary":
        return {"title": f"手填的汇总有 {s.get('仍需核对的人次')} 处和周表对不上",
                "noticed": "{文件} 的汇总表是手填的。按 {明细表数} 张周表重新加了一遍：{对不上的人次} 人次有出入" + ("，其中 {规则解释的人次} 人次能用“{折算规则}”解释，剩 {仍需核对的人次} 人次（{仍需核对的格数} 格）解释不了。" if F["rule_found"] else "。"),
                "prepared": "每个文件一份新表：原表不动，加了“自动汇总(公式)”和“差异核对”两张表，每处出入都列出了来自哪几周。",
                "verified": f"公式在 LibreOffice 里重算，和逐周相加的结果逐格一致（{r.get('verify_deid', {}).get('公式汇总与逐周相加一致的格数', '?')} 格）；原有工作表逐格未变。",
                "question": "以后要不要直接用公式汇总，不再手抄？", "options": ["以后用公式", "只看这次的差异", "不用"]}
    if k == "numbered_series":
        return {"title": f"{s.get('系列')}报告：{s.get('期数')} 期留下 {s.get('交付文件数')} 个报告文件",
                "noticed": "{多文件的期数} 期各有 2 个以上报告文件，前缀有 {命名写法数} 种写法；按节奏 {下一期} 约在 {下一期日期}。",
                "prepared": "每期报告文件清单（标出最新的、大小完全相同的副本）+ 一个开新一期的小脚本：从任务书文件名推出“{前缀}实验N_标题”，复制你的报告模板。",
                "verified": "用过去几期回放：编号和标题都能对上你当时交的文件名；演示模式不写文件，执行模式不覆盖已有文件。",
                "question": "下一期任务书到了，要不要自动帮你把文件夹和报告建好？", "options": ["要", "不用"]}
    return {"title": KIND_CN.get(k, k), "noticed": describe(f), "prepared": "", "verified": "", "question": "", "options": ["知道了"]}

# ============================================================= 第 9 轮：真实 Windows 回溯数据上补的检测器
DOC_OUT = {".doc", ".docx", ".wps", ".odt"}
SERIES_DIR = re.compile(r"(\D{1,12}?)\s*(\d{1,3})")

def _series_index(path):
    """路径里第一个“前缀+编号”的文件夹（实验4、Lab 3、第5周）→ (父路径, 前缀, 编号, 文件夹深度)"""
    parts = _p(path).parts
    for i, part in enumerate(parts[:-1]):
        m = SERIES_DIR.fullmatch(part)
        if m and i >= 1 and re.search(r"[A-Za-z\u4e00-\u9fa5]", m.group(1)):
            return "/".join(parts[:i]), m.group(1), int(m.group(2)), i
    return None

def detect_numbered_series(evs, meta):
    """同一个父文件夹下有一串编号文件夹（实验1…实验6），按时间一个接一个出现 → 例行的系列任务。
    看每一期留下了几个“交付类”文件（doc/docx）、命名写法有几种，并按过去节奏推测下一期。"""
    by = defaultdict(lambda: defaultdict(list))
    for e in _hist(evs):
        if not e.get("path") or e["type"] not in ("file_open", "file_save", "file_create"): continue
        s = _series_index(e["path"])
        if s: by[(s[0], s[1])][s[2]].append(e)
    out, now = [], meta["now_dt"]
    for (root, prefix), per in by.items():
        ns = sorted(per)
        if len(ns) < 4 or ns[-1] - ns[0] + 1 > len(ns) + 1: continue
        start = {n: min(e["dt"] for e in per[n]) for n in ns}
        ordered = sum(1 for a, b in zip(ns, ns[1:]) if start[b] >= start[a] - timedelta(hours=1)) / (len(ns) - 1)
        span = (start[ns[-1]] - start[ns[0]]).days
        if ordered < 0.8 or span < 10: continue
        step = span / (ns[-1] - ns[0])
        wd, wn = Counter(start[n].weekday() for n in ns).most_common(1)[0]
        if wn / len(ns) >= 0.5:
            nxt = now.date() + timedelta(days=(wd - now.weekday()) % 7 or 7) if start[ns[-1]].date() + timedelta(days=round(step)) <= now.date() else start[ns[-1]].date() + timedelta(days=(wd - start[ns[-1]].weekday()) % 7 or 7)
        else:
            nxt = (start[ns[-1]] + timedelta(days=round(step))).date()
        items = {}
        for n in ns:
            files = {}
            for e in per[n]:
                p = e["path"]; ext = _p(p).suffix.lower()
                if ext not in DOC_OUT or _p(p).name.startswith("~$"): continue
                f = files.setdefault(p, {"path": p, "saved": None, "size": None, "opened": 0})
                if e["type"] in ("file_save", "file_create"): f["saved"] = max(f["saved"] or e["dt"], e["dt"]); f["size"] = e.get("size") or f["size"]
                else: f["opened"] += 1
            items[n] = sorted(files.values(), key=lambda f: (f["saved"] or datetime.min))
        briefs = {}
        for n in ns:     # 每期最早出现的 pdf = 题目/任务书（只用来提取标题）
            pdfs = sorted({(min(e["dt"] for e in per[n] if e["path"] == p), p) for p in {e["path"] for e in per[n]} if _p(p).suffix.lower() == ".pdf"})
            if pdfs: briefs[n] = pdfs[0][1]
        # 报告 = 名字里带“前缀+编号”的文档（模板、截图汇总这类不算交付）
        num_re = re.compile(re.escape(prefix) + r"\s*(\d+|[一二三四五六七八九十]+)")
        reports = {n: [f for f in v if num_re.search(_p(f["path"]).stem)] for n, v in items.items()}
        multi = {n: len(v) for n, v in reports.items() if len(v) >= 2}
        same_size = sum(1 for v in reports.values() for a, b in zip(v, v[1:]) if a["size"] and a["size"] == b["size"])
        styles = Counter()
        for v in reports.values():
            for f in v:
                stem = _p(f["path"]).stem; m = num_re.search(stem)
                styles[(stem[:m.start()] or "（无前缀）") + ("〈中文数字〉" if not m.group(1).isdigit() else "")] += 1
        n_docs = sum(len(v) for v in reports.values())
        if n_docs < len(ns): continue          # 大部分期没有交付文件：只是浏览，不算
        out.append({"kind": "numbered_series", "score": 12 + len(ns) * 2 + len(multi) * 2 + min(6, len(styles) * 2) + (6 if 0 <= (nxt - now.date()).days <= 7 else 0),
            "local": {"root": root, "prefix": prefix, "numbers": ns, "starts": {n: start[n].strftime("%Y-%m-%d %H:%M") for n in ns},
                      "items": {n: [{"path": f["path"], "saved": f["saved"].strftime("%Y-%m-%d %H:%M") if f["saved"] else "", "size": f["size"]} for f in v] for n, v in items.items()},
                      "briefs": briefs, "styles": dict(styles), "next_n": ns[-1] + 1, "next_date": str(nxt), "weekday": wd},
            "facts": {"episodes": len(ns), "span_days": span, "days_per_episode": round(step, 1), "weekday": "周" + WD[wd], "weekday_share": round(wn / len(ns), 2),
                      "deliverable_files": n_docs, "episodes_with_multiple_files": len(multi), "max_files_one_episode": max(multi.values()) if multi else 1,
                      "identical_size_pairs": same_size, "naming_styles": len(styles), "next_in_days": (nxt - now.date()).days}})
    return out

def detect_duplicate_copies(evs, meta):
    """同名、同大小的文件出现在两个以上不同文件夹（比如同一份证书/表格同时放在两个材料文件夹）。
    这通常是有意的（同一份材料交两处），所以只记录、分数很低，不上清单；有内容副本时用哈希确认。"""
    by = defaultdict(set)
    for e in _hist(evs):
        if e["type"] in ("file_create", "file_save") and e.get("size") and "downloads" not in e.get("source", ""):
            by[(_p(e["path"]).name, e["size"])].add(str(_p(e["path"]).parent))
    groups = [(k, sorted(v)) for k, v in by.items() if len(v) >= 2]
    if not groups: return []
    return [{"kind": "duplicate_copies", "score": 4 + len(groups),
             "local": {"groups": [{"name": k[0], "size": k[1], "folders": v} for k, v in groups]},
             "facts": {"files": len(groups), "max_folders": max(len(v) for _, v in groups)}}]

DETECTORS += [detect_numbered_series, detect_duplicate_copies]
KIND_CN.update({"numbered_series": "一期接一期的系列任务", "duplicate_copies": "同一份文件放了好几处", "manual_summary": "手工汇总和明细对不上"})
