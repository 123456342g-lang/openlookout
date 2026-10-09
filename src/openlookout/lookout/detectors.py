"""b 段：确定性找规律。纯统计 / 规则，不用任何模型。
每个检测器输出 finding：
  kind, score(粗略价值分), local(含真实值，只在本机用), facts(结构化事实，交给脱敏层)
"""
import re, statistics
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .common import (ROOT, abspath, norm_title, read_table, read_text_any, to_num, to_date, watched_files)

BROWSERS = {"google-chrome", "chromium", "firefox", "microsoft-edge", "brave-browser", "tabbit"}  # 后三个来自 Windows 记录器/历史回溯

# ---------------------------------------------------------------- 1. 周期性"拼文件"
def detect_periodic_assembly(evs, meta):
    """找"新生成的文件"(编辑器第一次保存) → 回看它之前 2 小时里打开过的文件、粘贴进它的次数、花的时间。
    同一命名模式(数字→#)出现 ≥2 次且输入文件集合相近、间隔规律 → 周期性手工拼装。"""
    first_save, first_open = {}, {}
    for e in evs:
        if e["type"] == "file_open": first_open.setdefault(e["path"], e["dt"])
        # 真实记录器（inotify）在新建文件时也会先报一次 IN_OPEN：保存前 60 秒内的"打开"算作新建本身
        if e["type"] == "file_save" and e.get("app") not in BROWSERS and e["path"] not in first_save and \
           (e["path"] not in first_open or (e["dt"] - first_open[e["path"]]).total_seconds() <= 60):
            first_save[e["path"]] = e["dt"]
    groups = defaultdict(list)
    for p, t in first_save.items():
        groups[(str(Path(p).parent), norm_title(Path(p).name))].append((t, p))
    out = []
    for (folder, pattern), occ in groups.items():
        if len(occ) < 2: continue
        occ.sort(); sessions = []
        for t, p in occ:
            win = [e for e in evs if t - timedelta(hours=2) <= e["dt"] <= t + timedelta(minutes=30)]
            name = Path(p).name
            inputs = {e["path"] for e in win if e["type"] == "file_open" and e["path"] != p and e["dt"] <= t
                      and not norm_title(Path(e["path"]).name) == pattern}
            pastes = [e for e in win if e["type"] == "clipboard" and name in (e.get("dst_title") or "") and e["dt"] <= t]
            # 会话起点 = 第一次打开输入文件；时长 = 起点到保存
            starts = [e["dt"] for e in win if e["type"] == "file_open" and e["path"] in inputs and e["dt"] <= t]
            minutes = (t - min(starts)).total_seconds() / 60 if starts else 0
            calc_switches = sum(1 for e in win if e["type"] == "focus" and e["dt"] <= t and e["dt"] >= (min(starts) if starts else t))
            helper_apps = {e["app"] for e in win if e["type"] == "focus" and e["app"] not in ("libreoffice-calc",) and e["dt"] <= t and starts and e["dt"] >= min(starts)}
            sessions.append({"t": t, "path": p, "inputs": inputs, "pastes": len(pastes), "minutes": round(minutes),
                             "switches": calc_switches, "helper_apps": helper_apps})
        common = set.intersection(*[s["inputs"] for s in sessions])
        if len(common) < 2: continue
        gaps = [round((b["t"] - a["t"]).total_seconds() / 86400) for a, b in zip(sessions, sessions[1:])]
        wd = Counter(s["t"].weekday() for s in sessions).most_common(1)[0]
        period = statistics.median(gaps) if gaps else None
        regular = period and all(abs(g - period) <= 1 for g in gaps)
        if not regular: continue
        nxt = sessions[-1]["t"] + timedelta(days=period)
        mins = statistics.mean(s["minutes"] for s in sessions)
        out.append({"kind": "periodic_assembly", "score": mins * 30 / period,
            "local": {"pattern": pattern, "folder": folder, "outputs": [s["path"] for s in sessions], "inputs": sorted(common),
                      "sessions": [{"date": s["t"].strftime("%m-%d %a %H:%M"), "minutes": s["minutes"], "pastes": s["pastes"],
                                     "switches": s["switches"], "helpers": sorted(s["helper_apps"])} for s in sessions],
                      "period_days": period, "weekday": wd[0], "next_due": nxt.isoformat(),
                      "due_now": nxt.date() <= meta["now_dt"].date()},
            "facts": {"occurrences": len(sessions), "period_days": period, "weekday": "周" + "一二三四五六日"[wd[0]],
                      "avg_minutes": round(mins), "avg_pastes": round(statistics.mean(s["pastes"] for s in sessions)),
                      "avg_window_switches": round(statistics.mean(s["switches"] for s in sessions)),
                      "n_inputs": len(common), "due_today": nxt.date() <= meta["now_dt"].date()}})
    return out

# ---------------------------------------------------------------- 2. 跨应用复制粘贴摩擦
def detect_copy_paste_friction(evs, meta, assembly_outputs=()):
    pairs = defaultdict(list)
    for e in evs:
        if e["type"] != "clipboard": continue
        if any(Path(o).name in (e.get("dst_title") or "") for o in assembly_outputs):
            continue  # 已经算进"周期性拼文件"里了
        key = (e["src_app"], norm_title(e["src_title"]), e["dst_app"], norm_title(e["dst_title"]))
        pairs[key].append(e)
    out = []
    for (sa, st, da, dt_), lst in pairs.items():
        days = {e["dt"].date() for e in lst}
        if len(lst) < 15 or len(days) < 2: continue
        # 粘贴后 60 秒内同一网页里被编辑的字段标签（浏览器扩展采集）
        labels = Counter()
        for e in lst:
            nxt = next((f for f in evs if f["type"] == "form_edit" and f["via"] == "paste" and e["dt"] <= f["dt"] <= e["dt"] + timedelta(seconds=60)), None)
            if nxt: labels[nxt["field_label"]] += 1
        # 来源文档：同模式窗口对应的文件
        src_files = sorted({f["path"] for f in evs if f["type"] == "file_open" and f.get("app") == sa and norm_title(Path(f["path"]).name + " — ") [:10] and
                            any(Path(f["path"]).name in (x["src_title"] or "") for x in lst)})
        # 同目录、同命名模式但从未被抄过的文档 = 可能漏办
        pending = []
        if src_files:
            folder = abspath(src_files[0]).parent
            pat = norm_title(Path(src_files[0]).name)
            done_names = {Path(p).name for p in src_files}
            pending = sorted(str(p.relative_to(ROOT / "sim_home")) for p in folder.iterdir() if norm_title(p.name) == pat and p.name not in done_names)
        per_doc = len(lst) / max(1, len(src_files))
        dst_url = next((f.get("url") for f in evs if f["type"] == "focus" and f["app"] == da and f["title"] and norm_title(f["title"]) == dt_ and f.get("url")), None)
        secs = sum(((lst[i + 1]["dt"] - lst[i]["dt"]).total_seconds()) for i in range(len(lst) - 1) if (lst[i + 1]["dt"] - lst[i]["dt"]).total_seconds() < 300)
        out.append({"kind": "copy_paste_friction", "score": len(lst) * 0.5 + len(pending) * 10,
            "local": {"src_app": sa, "src_title": st, "dst_app": da, "dst_title": dt_, "dst_url": dst_url, "n": len(lst),
                      "days": sorted(str(d) for d in days), "labels": dict(labels), "src_files": src_files, "pending": pending,
                      "samples": [(e["src_title"], e.get("text")) for e in lst]},
            "facts": {"src_kind": "PDF/文档查看器" if sa == "evince" else ("聊天软件" if sa == "wechat" else sa),
                      "dst_kind": "浏览器网页表单" if da in BROWSERS else ("表格" if "calc" in da else da),
                      "pastes": len(lst), "days": len(days), "docs": len(src_files), "fields_per_doc": round(per_doc, 1),
                      "field_labels": list(labels), "pending_docs": len(pending), "minutes_spent_est": round(secs / 60)}})
    return out

# ---------------------------------------------------------------- 3. 重复查询
def _norm_q(q): return re.sub(r"[\s的]+", "", q.lower())
def detect_repeated_lookup(evs, meta):
    qs = []
    for e in evs:
        if e["type"] != "focus" or not e.get("url"): continue
        if e.get("transition") == "reload": continue   # 刷新/浏览器重启恢复标签页，不是又搜了一次（历史回溯数据里很多）
        u = urlparse(e["url"]); p = parse_qs(u.query)
        q = (p.get("wd") or p.get("q") or p.get("query") or [None])[0]
        if q:
            q = q.replace("+", " ")
            if qs and _norm_q(qs[-1][1]) == _norm_q(q) and (e["dt"] - qs[-1][0]["dt"]).total_seconds() < 120: continue   # 同一次搜索被两个浏览器/两次加载记了两遍
            qs.append((e, q))
    # 导航式搜索：把搜索框当地址栏用（搜 "github" 然后点进 github.com）。同一个词每次搜完都去同一个站点、而且站点名/标题里就含这个词，
    # 这不是“反复查一个答案”，而是习惯；没有剪贴板数据时尤其不能当成查资料（第 9 轮，真实 Windows 回溯里这类占了大多数）
    focus = [e for e in evs if e["type"] == "focus" and e.get("url")]
    pos = {id(e): i for i, e in enumerate(focus)}
    def _dest(e):
        i = pos.get(id(e))
        if i is None: return None
        for x in focus[i + 1:i + 6]:
            if (x["dt"] - e["dt"]).total_seconds() > 180: break
            h = (urlparse(x["url"]).hostname or "").lower()
            if h and h != (urlparse(e["url"]).hostname or "").lower(): return h, (x.get("title") or "").lower()
        return None
    def _navigational(lst):
        dests = [_dest(e) for e, _ in lst]; hosts = Counter(d[0] for d in dests if d)
        if not hosts: return False
        top, n = hosts.most_common(1)[0]
        q = re.sub(r"[^0-9a-z一-龥]", "", lst[0][1].lower())
        named = any(q and (q in re.sub(r"[^0-9a-z]", "", h) or q in t) for h, t in (d for d in dests if d))
        hits = sum(1 for d in dests if d and q and (q in re.sub(r"[^0-9a-z]", "", d[0]) or q in d[1]))
        return named and (n >= 0.6 * len(lst) or hits >= 0.6 * len(lst))   # 镜像站换域名（.sk/.im）时按“去的站名里含这个词”算
    qs_all = qs
    nav = defaultdict(list)
    for e, q in qs_all: nav[_norm_q(q)].append((e, q))
    nav_keys = {k for k, lst in nav.items() if len(lst) >= 3 and _navigational(lst)}
    meta.setdefault("_navigational_searches", {})
    for k in nav_keys: meta["_navigational_searches"][k] = len(nav[k])
    qs = [(e, q) for e, q in qs_all if _norm_q(q) not in nav_keys]
    # 每次查询之后 3 分钟内，有没有从浏览器复制一个"答案"粘进别的程序
    ans = {}
    for e, q in qs:
        c = next((x for x in evs if x["type"] == "clipboard" and x["src_app"] in BROWSERS and e["dt"] <= x["dt"] <= e["dt"] + timedelta(minutes=3)), None)
        if c: ans[id(e)] = c
    out, used = [], set()
    # 3a. 同一个"属性词"被拿来查不同对象（X 摩尔质量 / Y 摩尔质量…）——把查询看成 实体+属性
    suffix_groups = defaultdict(list)
    for e, q in qs:
        parts = q.split()
        if len(parts) >= 2: suffix_groups[parts[-1]].append((e, q))
    for e, q in qs:  # 没空格的 "硼氢化钠摩尔质量"：用已知属性词切开
        if " " not in q:
            for attr in list(suffix_groups):
                if q.endswith(attr) and len(q) > len(attr): suffix_groups[attr].append((e, q))
    for attr, lst in sorted(suffix_groups.items(), key=lambda kv: -len(kv[1])):
        lst = [x for x in lst if id(x[0]) not in used]
        # 迭代 1：同一个答案被粘贴过的其它说法（"NaBH4 分子量" 与 "硼氢化钠 摩尔质量" 粘的是同一个数）并入同一族
        vals = {ans[id(e)]["hash"] for e, _ in lst if id(e) in ans}
        lst += [(e, q) for e, q in qs if id(e) in ans and ans[id(e)]["hash"] in vals and (e, q) not in lst and id(e) not in used]
        days = {e["dt"].date() for e, _ in lst}
        if len(lst) < 6 or len(days) < 4: continue
        if not any(" " in q for _, q in lst if q.endswith(attr)) or sum(1 for _, q in lst if " " in q) < 3: continue   # 没有空格的单词（产品名）不是“X 的属性”
        dwell = statistics.median(e["dur_s"] for e, _ in lst)
        if dwell > 180: continue   # 迭代 1：停留很久的是"读"，不是"查一个答案"
        pasted = Counter(ans[id(e)].get("text", ans[id(e)]["hash"]) for e, _ in lst if id(e) in ans)
        targets = Counter(ans[id(e)]["dst_title"] for e, _ in lst if id(e) in ans)
        for e, _ in lst: used.add(id(e))
        ents = len(pasted) or len({q for _, q in lst})
        out.append({"kind": "repeated_lookup", "score": len(lst) * 1.5,
            "local": {"attr": attr, "queries": Counter(q for _, q in lst).most_common(), "days": sorted(str(d) for d in days),
                      "pasted_values": dict(pasted), "paste_targets": dict(targets), "median_dwell_s": dwell},
            "facts": {"attribute": attr, "searches": len(lst), "distinct_answers": ents, "days": len(days),
                      "answer_pasted_into": "表格" if targets else None, "pastes_after_search": sum(pasted.values()),
                      "median_dwell_s": dwell}})
    # 3b. 完全相同的短查询反复出现
    same = defaultdict(list)
    for e, q in qs:
        if id(e) not in used: same[_norm_q(q)].append((e, q))
    for k, lst in same.items():
        days = {e["dt"].date() for e, _ in lst}
        dwell = statistics.median(e["dur_s"] for e, _ in lst)
        if len(lst) >= 3 and len(days) >= 3 and dwell <= 180:
            out.append({"kind": "repeated_lookup", "score": len(lst),
                "local": {"attr": None, "queries": [(lst[0][1], len(lst))], "days": sorted(str(d) for d in days), "pasted_values": {}, "paste_targets": {}, "median_dwell_s": dwell},
                "facts": {"attribute": None, "searches": len(lst), "distinct_answers": 1, "days": len(days), "answer_pasted_into": None,
                          "pastes_after_search": 0, "median_dwell_s": dwell}})
    return out

# ---------------------------------------------------------------- 4. 账单：重复扣费 / 悄悄涨价
BILL_COLS = {"date": ["交易时间", "交易日期", "时间", "日期"], "party": ["交易对方", "商户", "对方", "商户名称"],
             "desc": ["商品说明", "商品", "摘要", "备注"], "amount": ["金额", "金额(元)", "交易金额"], "order": ["交易订单号", "订单号", "流水号"]}
def _col(header, names):
    for n in names:
        for i, h in enumerate(header):
            if h == n or h.startswith(n): return i
    return None
def recurring_charges(meta):
    rows = _bill_rows(meta); by = defaultdict(list)
    for r in rows: by[(r["party"], r["desc"])].append(r)
    out = []
    for k, lst in by.items():
        months = Counter(r["d"].strftime("%Y-%m") for r in lst)
        if len(months) >= 2 and max(months.values()) <= 2: out += lst
    return out

def _bill_rows(meta):
    rows, seen = [], set()
    for p in watched_files(meta):
        if p.suffix != ".csv": continue
        header, data = read_table(p)
        ix = {k: _col(header, v) for k, v in BILL_COLS.items()}
        if None in (ix["date"], ix["party"], ix["amount"]): continue
        for r in data:
            d = to_date(r[ix["date"]]); a = to_num(r[ix["amount"]])
            if not d or a is None: continue
            oid = r[ix["order"]] if ix["order"] is not None else None
            if oid and oid in seen: continue
            seen.add(oid)
            rows.append({"t": str(r[ix["date"]]), "d": d, "party": r[ix["party"]], "desc": r[ix["desc"]] if ix["desc"] is not None else "",
                         "amount": a, "order": oid, "file": p.name})
    return rows

def detect_bills(evs, meta):
    rows = _bill_rows(meta)
    if not rows: return []
    by = defaultdict(list)
    for r in rows: by[(r["party"], r["desc"])].append(r)
    out = []
    for (party, desc), lst in by.items():
        lst.sort(key=lambda r: r["t"])
        months = Counter(r["d"].strftime("%Y-%m") for r in lst)
        # "周期性收费"：至少两个月出现，且每月最多 2 笔（排除食堂、外卖这种高频消费）
        if len(months) < 2 or max(months.values()) > 2: continue
        dups = [(a, b) for a, b in zip(lst, lst[1:]) if a["amount"] == b["amount"] and (b["d"] - a["d"]).days <= 1]
        for a, b in dups:
            out.append({"kind": "duplicate_charge", "score": 50 + a["amount"],
                "local": {"party": party, "desc": desc, "rows": [a, b], "history": lst},
                "facts": {"merchant_type": "订阅/会员自动续费" if "续费" in desc or "会员" in desc else "周期性收费",
                          "merchant": party, "times_same_day": 2, "gap_seconds": None, "normal_per_month": 1}})
        monthly = [(m, [r for r in lst if r["d"].strftime("%Y-%m") == m]) for m in sorted(months)]
        for (m1, r1), (m2, r2) in zip(monthly, monthly[1:]):
            a1, a2 = r1[0]["amount"], r2[0]["amount"]
            if a1 != a2:
                out.append({"kind": "price_change", "score": 30 + abs(a2 - a1) * 12,
                    "local": {"party": party, "desc": desc, "before": r1[0], "after": r2[0]},
                    "facts": {"merchant": party, "merchant_type": "订阅/会员自动续费" if "续费" in desc or "会员" in desc else "周期性收费",
                              "change_pct": round((a2 - a1) / a1 * 100), "months": [m1, m2]}})
    return out

# ---------------------------------------------------------------- 5. 埋在笔记里的截止日 / 承诺
DL_KW = re.compile(r"(前|之前|截止|以前|deadline|到期|定在|due\s*(?:date|by)?|submit\s*by)", re.I)
CN_DATE = re.compile(r"(?:(20\d\d)\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
EN_DATE = re.compile(
    r"(?:deadline|due(?:\s*date)?|submit\s*by|due\s*by)\s*[:：]?\s*"
    r"(?:(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})"
    r"|(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})"
    r"|(20\d{2})[-/](\d{1,2})[-/](\d{1,2}))",
    re.I,
)
_EN_MON = {m.lower(): i for i, m in enumerate(
    "January February March April May June July August September October November December".split(), 1)}
def _ngrams(s, n=(2, 3, 4)):
    s2 = re.sub(r"[\s，。、：:；;（）()\"“”'‘’,.!！？?]", "|", s)
    out = set()
    for seg in s2.split("|"):
        for k in n:
            out |= {seg[i:i + k] for i in range(len(seg) - k + 1)}
    out |= set(re.findall(r"[A-Za-z]{2,}", s))
    return out
STOP = set("我们大家这批之前以前一下统一整理一张交到要排到过了这学期别忘了完成定在初稿老师")
def detect_deadlines(evs, meta):
    now = meta["now_dt"]; aliases = meta["user_aliases"]
    out = []
    # 所有事件里出现过的文本（窗口标题、网址、文件名）—— 用来判断"之后有没有跟进"
    trail = [(e["dt"], " ".join(str(e.get(k) or "") for k in ("title", "url", "path"))) for e in evs]
    for p in watched_files(meta):
        if p.suffix.lower() not in (".md", ".txt", ".docx") or p.name.startswith("dzfp_"): continue
        saved = max([e["dt"] for e in evs if e.get("path", "").endswith(p.name) and e["type"] == "file_save"] or [None]) if True else None
        if saved is None: continue
        for line in read_text_any(p).splitlines():
            for sent in re.split(r"[。；;]", line):
                if not DL_KW.search(sent): continue
                for m in CN_DATE.finditer(sent):
                    y = int(m.group(1) or now.year); mo, d = int(m.group(2)), int(m.group(3))
                    try: due = now.replace(year=y, month=mo, day=d, hour=23, minute=59)
                    except ValueError: continue
                    # 截止词要紧跟日期（"9月28日前"），排除"定在 11 月 20 日"之外的普通日期
                    tail = sent[m.end():m.end() + 4]
                    if not DL_KW.search(tail) and "定在" not in sent[:m.start()]: continue
                    days_left = (due.date() - now.date()).days
                    mine = any(a in sent for a in aliases) or not re.search(r"[\u4e00-\u9fa5]{2,3}[:：]", sent)
                    grams = {g for g in _ngrams(sent) if len(g) >= 3 or re.match(r"[A-Za-z]", g)}
                    grams = {g for g in grams if not set(g) <= STOP and not any(a in g for a in aliases) and not re.search(r"\d", g)}
                    follow = sorted({g for g in grams for t, txt in trail if t > saved and g in txt})
                    if any(o["local"]["sentence"] == sent.strip(" -") and 0 <= o["local"]["days_left"] <= days_left for o in out): continue
                    out[:] = [o for o in out if not (o["local"]["sentence"] == sent.strip(" -"))]
                    out.append({"kind": "deadline", "score": (100 if 0 <= days_left <= 7 else 30 if 0 <= days_left <= 14 else 5) * (1 if not follow else 0.1) * (1 if mine else 0.3),
                        "local": {"file": p.name, "sentence": sent.strip(" -"), "due": due.date().isoformat(), "days_left": days_left,
                                  "noted_on": saved.strftime("%m-%d"), "followup_hits": follow, "assigned_to_user": mine},
                        "facts": {"days_left": days_left, "assigned_to_user": mine, "has_followup_activity": bool(follow),
                                  "source": "组会纪要" if "纪要" in p.name else "笔记"}})
                # English "Deadline: 20 November 2023" / "due by March 1, 2024"
                for m in EN_DATE.finditer(sent):
                    try:
                        if m.group(2):  # day Month year
                            d, mo, y = int(m.group(1)), _EN_MON[m.group(2).lower()], int(m.group(3))
                        elif m.group(4):  # Month day, year
                            mo, d, y = _EN_MON[m.group(4).lower()], int(m.group(5)), int(m.group(6))
                        else:
                            y, mo, d = int(m.group(7)), int(m.group(8)), int(m.group(9))
                        due = now.replace(year=y, month=mo, day=d, hour=23, minute=59)
                    except (ValueError, KeyError, TypeError):
                        continue
                    days_left = (due.date() - now.date()).days
                    sent_c = sent.strip(" -")
                    mine = True
                    grams = {g for g in _ngrams(sent_c) if len(g) >= 3 or re.match(r"[A-Za-z]", g)}
                    grams = {g for g in grams if not set(g) <= STOP and not re.search(r"\d", g)}
                    follow = sorted({g for g in grams for t, txt in trail if t > saved and g in txt})
                    if any(o["local"]["sentence"] == sent_c for o in out): continue
                    # Far-future deadlines still matter if the form was opened (score floor 12)
                    base = 100 if 0 <= days_left <= 7 else 40 if 0 <= days_left <= 30 else 25 if days_left > 30 else 5
                    # English form deadlines: follow-up n-gram matching is noisy on academic PDFs; keep a floor
                    score = base if not follow else max(18, base * 0.5)
                    out.append({"kind": "deadline", "score": score,
                        "local": {"file": p.name, "sentence": sent_c, "due": due.date().isoformat(), "days_left": days_left,
                                  "noted_on": saved.strftime("%m-%d"), "followup_hits": follow, "assigned_to_user": mine},
                        "facts": {"days_left": days_left, "assigned_to_user": mine, "has_followup_activity": bool(follow),
                                  "source": "表单/文档" if "Form" in p.name or "form" in p.name.lower() else "笔记"}})
    return out

# ---------------------------------------------------------------- 6. 数值漂移（按类别分组的变点检测）
def detect_numeric_drift(evs, meta):
    out = []
    for p in watched_files(meta):
        if p.suffix not in (".xlsx", ".csv") or p.name.startswith("周报"): continue
        try: header, data = read_table(p)
        except Exception: continue
        if len(data) < 20: continue
        dcol = next((i for i, h in enumerate(header) if any(to_date(r[i]) for r in data[:5])), None)
        if dcol is None: continue
        cats = [i for i, h in enumerate(header) if 1 < len({r[i] for r in data}) <= 6 and all(isinstance(r[i], str) for r in data if r[i])]
        nums = [i for i, h in enumerate(header) if sum(to_num(r[i]) is not None for r in data) > 0.9 * len(data)]
        # 迭代 1：排除"编号型"数值列（几乎每行都不同的整数 / 超长数字，如订单号）
        nums = [i for i in nums if not (len({r[i] for r in data}) > 0.9 * len(data) and all(float(to_num(r[i])).is_integer() for r in data if to_num(r[i]) is not None))]
        seen_groups = set()
        for ci in cats:
            for val in {r[ci] for r in data if r[ci]}:
                grp = sorted([r for r in data if r[ci] == val], key=lambda r: str(r[dcol]))
                if len(grp) < 10: continue
                sig = tuple(map(str, grp))
                if sig in seen_groups: continue   # 迭代 1："类型=对照" 与 "试剂=柠檬酸钠" 其实是同一批行
                seen_groups.add(sig)
                for ni in nums:
                    ys = [to_num(r[ni]) for r in grp]
                    if len(set(ys)) < 4: continue
                    best = None
                    for k in range(5, len(ys) - 4):
                        a, b = ys[:k], ys[k:]
                        sd = statistics.pstdev(a) or 1e-9
                        z = (statistics.mean(b) - statistics.mean(a)) / sd
                        mono = sum(1 for x, y in zip(b, b[1:]) if y >= x) / (len(b) - 1)
                        if abs(z) > 4 and (best is None or abs(z) > abs(best[1])): best = (k, z, mono)
                    if not best: continue
                    k, z, mono = best
                    base = statistics.mean(ys[:k]); last = ys[-1]; sd0 = statistics.pstdev(ys[:k])
                    k = next((j for j in range(k, len(ys)) if abs(ys[j] - base) > 3 * sd0), k)  # 偏离起点
                    n_after = sum(1 for r in data if str(r[dcol]) >= str(grp[k][dcol]))
                    out.append({"kind": "numeric_drift", "score": 60 + min(40, abs(z)),
                        "local": {"file": p.name, "group_col": header[ci], "group_val": val, "value_col": header[ni], "date_col": header[dcol],
                                  "since": str(grp[k][dcol]), "baseline": round(base, 4), "baseline_sd": round(statistics.pstdev(ys[:k]), 4),
                                  "latest": last, "series": [(str(r[dcol]), to_num(r[ni])) for r in grp], "rows_after": n_after},
                        "facts": {"group_is_reference": None, "z": round(z, 1), "pct_change": round((last - base) / base * 100, 1),
                                  "trend_monotonic_ratio": round(mono, 2), "points_before": k, "points_after": len(ys) - k,
                                  "other_rows_since_change": n_after}})
    return out


# ---------------------------------------------------------------- 7. 跨应用粘贴（按 App 对聚合，标题碎片化时仍能发现）
def detect_cross_app_paste(evs, meta):
    """真实数据里窗口标题经常变，按 (src_app, dst_app) 聚合；排除同 App 内粘贴。"""
    pairs = defaultdict(list)
    for e in evs:
        if e["type"] != "clipboard": continue
        if e["src_app"] == e["dst_app"]: continue
        if e["src_app"] in ("werfault", "searchapp") or e["dst_app"] in ("werfault", "searchapp"): continue
        pairs[(e["src_app"], e["dst_app"])].append(e)
    out = []
    for (sa, da), lst in pairs.items():
        days = {e["dt"].date() for e in lst}
        if len(lst) < 12 or len(days) < 2: continue
        src_titles = Counter(norm_title(e.get("src_title") or "") for e in lst).most_common(3)
        dst_titles = Counter(norm_title(e.get("dst_title") or "") for e in lst).most_common(3)
        secs = sum(((lst[i+1]["dt"] - lst[i]["dt"]).total_seconds()) for i in range(len(lst)-1)
                   if 0 < (lst[i+1]["dt"] - lst[i]["dt"]).total_seconds() < 300)
        out.append({"kind": "copy_paste_friction", "score": len(lst) * 0.8 + len(days) * 3,
            "local": {"src_app": sa, "src_title": src_titles[0][0] if src_titles else "", "dst_app": da,
                      "dst_title": dst_titles[0][0] if dst_titles else "", "dst_url": None, "n": len(lst),
                      "days": sorted(str(d) for d in days), "labels": {}, "src_files": [], "pending": [],
                      "samples": [(e["src_title"], e.get("text")) for e in lst[:8]]},
            "facts": {"src_kind": sa, "dst_kind": da, "pastes": len(lst), "days": len(days), "docs": 0,
                      "fields_per_doc": 0, "field_labels": [], "pending_docs": 0,
                      "minutes_spent_est": round(secs / 60)}})
    return out

# ---------------------------------------------------------------- 8. 窗口来回撕扯（同一对文档/App 高频切换）
def detect_window_thrash(evs, meta):
    """在短窗口内两两切换焦点很多次 = 手工搬数据/对照阅读的摩擦。"""
    focuses = [e for e in evs if e["type"] == "focus"]
    # 滑动 20 分钟窗，统计相邻切换对
    buckets = defaultdict(list)  # (day, pair) -> switches with timestamps
    for a, b in zip(focuses, focuses[1:]):
        gap = (b["dt"] - a["dt"]).total_seconds()
        if gap > 1200 or gap < 0: continue
        ta, tb = norm_title(a.get("title") or ""), norm_title(b.get("title") or "")
        if not ta or not tb or ta == tb: continue
        if len(ta) < 6 or len(tb) < 6: continue
        # skip pure browser chrome noise
        if ta in ("New Tab - Google Chrome", "about:blank - Google Chrome") or tb in ("New Tab - Google Chrome", "about:blank - Google Chrome"):
            continue
        pair = tuple(sorted([(a["app"], ta), (b["app"], tb)]))
        buckets[(a["dt"].date(), pair)].append(a["dt"])
    # 再按 pair 跨天聚合
    by_pair = defaultdict(list)
    for (day, pair), times in buckets.items():
        if len(times) >= 8:
            by_pair[pair].append((day, len(times)))
    out = []
    for pair, days in by_pair.items():
        if len(days) < 2 and sum(n for _, n in days) < 40: continue
        if len(days) < 2: continue
        total = sum(n for _, n in days)
        (a_app, a_t), (b_app, b_t) = pair
        out.append({"kind": "window_thrash", "score": min(80, total * 0.4 + len(days) * 5),
            "local": {"a_app": a_app, "a_title": a_t, "b_app": b_app, "b_title": b_t,
                      "days": [{"day": str(d), "switches": n} for d, n in sorted(days)], "total_switches": total},
            "facts": {"app_a": a_app, "app_b": b_app, "days": len(days), "switches": total,
                      "title_a_short": a_t[:40], "title_b_short": b_t[:40]}})
    return out

# ---------------------------------------------------------------- 9. 多日反复打开同一类文档（无 file_save 也能发现）
def detect_recurring_doc_focus(evs, meta):
    """同一归一化窗口标题在 ≥3 天出现，且累计停留 ≥30 分钟 → 周期性工作。"""
    by = defaultdict(list)
    for e in evs:
        if e["type"] != "focus": continue
        t = norm_title(e.get("title") or "")
        if len(t) < 10: continue
        noise = ("New Tab", "NO_TITLE", "File Explorer", "Postvak IN", "Inbox", "Lock Screen", "about:blank", "Search",
                 "Program Manager", "cSpaces", "Zoom Meeting", "Google Scholar", "Mail -", "Gmail", "WhatsApp",
                 "Telegram", "Slack", "Teams", "Postvak", "Agenda -")
        if any(n in t for n in noise): continue
        if e["app"] in ("telegram", "slack", "teams", "zoom", "kmplayer64", "lync", "cspaces", "javaw"): continue
        by[(e["app"], t)].append(e)
    out = []
    for (app, title), lst in by.items():
        days = sorted({e["dt"].date() for e in lst})
        if len(days) < 4: continue
        mins = sum(e.get("dur_s") or 0 for e in lst) / 60
        if mins < 30: continue
        # gaps between active days
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        med = statistics.median(gaps) if gaps else None
        out.append({"kind": "recurring_doc_focus", "score": min(70, mins / 3 + len(days) * 2),
            "local": {"app": app, "title": title, "days": [str(d) for d in days], "minutes": round(mins),
                      "occurrences": len(lst), "median_gap_days": med},
            "facts": {"app": app, "title_short": title[:50], "days": len(days), "minutes": round(mins),
                      "median_gap_days": med}})
    return out


def run_all(evs, meta):
    fs = detect_periodic_assembly(evs, meta)
    outs = [o for f in fs for o in f["local"].get("outputs", [])]
    fs += detect_copy_paste_friction(evs, meta, outs)
    fs += detect_cross_app_paste(evs, meta)
    fs += detect_repeated_lookup(evs, meta)
    fs += detect_bills(evs, meta)
    fs += detect_deadlines(evs, meta)
    fs += detect_numeric_drift(evs, meta)
    fs += detect_window_thrash(evs, meta)
    fs += detect_recurring_doc_focus(evs, meta)
    # 去重：同 kind + 近似 facts 保留高分
    fs.sort(key=lambda f: -f["score"])
    kept, seen = [], set()
    for f in fs:
        key = (f["kind"], json_safe_key(f))
        if key in seen: continue
        seen.add(key); kept.append(f)
    for i, f in enumerate(kept): f["id"] = f"F{i+1}"
    return kept

def json_safe_key(f):
    import json as _json
    try:
        return _json.dumps(f.get("facts") or {}, ensure_ascii=False, sort_keys=True, default=str)[:240]
    except Exception:
        return f["kind"]
