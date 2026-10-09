"""已办清单：把卡片渲染成本地静态网页 + Markdown。真实值在这里（本机）填进模型写的占位符。"""
import html, json, re, shutil
from pathlib import Path
import openpyxl

URG = {"高": 0, "中": 1, "低": 2}
KIND_CN = {"periodic_assembly": "重复的活", "report_mismatch": "数字对不上", "copy_paste_friction": "来回复制粘贴", "repeated_lookup": "反复查同一类东西",
           "deadline": "快到期的事", "duplicate_charge": "重复扣费", "price_change": "悄悄涨价", "numeric_drift": "数据在漂",
           "window_thrash": "窗口来回撕扯", "recurring_doc_focus": "反复盯着同一件事"}

def fill(text, slots):
    text = str(text or "")
    for k, v in slots.items(): text = text.replace("{" + k + "}", str(v))
    text = re.sub(r"\{[^{}]{1,12}\}", "", text)
    text = text.replace("%%", "%")
    text = re.sub(r"(分钟|元|次|天|行)\s*\1", r"\1", text)   # 占位符本身带单位，模型又补了一次
    return text

def order(summary):
    cards = summary["cards"]; res = summary["results"]; judge = summary["judge"]
    fsc = {f["id"]: f["score"] for f in summary["findings"]}
    ids = [i for i in cards if i in res and res[i]["status"] not in ("failed", "skipped", "omit")]
    ids.sort(key=lambda i: (URG.get(judge.get(i, {}).get("urgency"), 3), res[i]["status"] != "verified", -fsc.get(i, 0)))
    return ids

def evidence(f, r):
    L = f["local"]; k = f["kind"]; ev = []
    if k == "periodic_assembly":
        for s in L["sessions"]: ev.append(f"{s['date']}：{s['minutes']} 分钟，切换窗口 {s['switches']} 次，粘贴 {s['pastes']} 次，用到 {', '.join(s['helpers'])}")
        ev.append("每次都打开：" + "、".join(Path(p).name for p in L["inputs"]))
    elif k == "report_mismatch":
        w = L.get("why") or {}
        ev.append(f"{Path(L['hand_file']).name} 里「{L['label']}」你写的是 {L['hand']}，按源表算是 {L['gen']}")
        for row in w.get("rows", []): ev.append(("源表里正好差这一行：" if len(w["rows"]) == 1 else "差额等于这一行（候选）：") + "，".join(f"{a}={b}" for a, b in row.items() if b not in (None, "")))
    elif k == "copy_paste_friction":
        days = "、".join(L.get("days") or [])
        labs = "、".join(L.get("labels") or [])
        ev.append(f"{days} 共粘贴 {L['n']} 次" + (f"，字段：{labs}" if labs else f"：{L.get('src_app')} → {L.get('dst_app')}"))
        ev += [f"还没报：{Path(p).name}" for p in L.get("pending") or []]
    elif k == "repeated_lookup":
        ev.append("搜过的：" + "、".join(f"「{q}」×{n}" for q, n in L["queries"][:6]))
        ev.append(f"{len(L['days'])} 天：{L['days'][0]} ~ {L['days'][-1]}；搜完都粘进了：{'、'.join(L['paste_targets'])}")
    elif k == "deadline":
        ev.append(f"{L['file']}（{L['noted_on']}）原话：「{L['sentence']}」")
        ev.append(f"之后 {L['noted_on']} 至今：你的电脑上没有出现「测试中心」「送样」相关的网页、文件或窗口" if not L["followup_hits"] else f"之后的相关操作：{L['followup_hits'][:3]}")
    elif k == "duplicate_charge":
        for x in L["rows"]: ev.append(f"{x['t']} {x['party']} {x['desc']} {x['amount']:.2f} 元 订单号 {x['order']}（{x['file']}）")
    elif k == "price_change":
        for x in (L["before"], L["after"]): ev.append(f"{x['t']} {x['party']} {x['desc']} {x['amount']:.2f} 元（{x['file']}）")
    elif k == "numeric_drift":
        ev.append(f"{L['file']} · {L['group_col']}={L['group_val']} · {L['value_col']}：" + "，".join(f"{d[5:]} {v}" for d, v in L["series"]))
    elif k == "window_thrash":
        ev.append(f"{L['a_app']}「{L['a_title'][:50]}」 ↔ {L['b_app']}「{L['b_title'][:50]}」")
        ev += [f"{d['day']}：切换 {d['switches']} 次" for d in L.get("days", [])[:6]]
    elif k == "recurring_doc_focus":
        ev.append(f"{L['app']}「{L['title'][:60]}」· {L['minutes']} 分钟 · {len(L.get('days', []))} 天")
        ev.append("出现日期：" + "、".join(L.get("days", [])[:8]))
    return ev

def preview(f, r, prep_rel):
    k = f["kind"]
    def xl_table(path, maxrows=8):
        ws = openpyxl.load_workbook(path).active; rows = [r_ for r_ in ws.iter_rows(values_only=True) if any(c is not None for c in r_)]
        out = "<table class='pv'>" + "".join("<tr>" + "".join(f"<td>{html.escape('' if c is None else str(c))}</td>" for c in row) + "</tr>" for row in rows[:maxrows]) + "</table>"
        return out + (f"<div class='more'>…共 {len(rows)} 行</div>" if len(rows) > maxrows else "")
    try:
        if k == "periodic_assembly" and r.get("this_week"): return xl_table(r["this_week"], 16)
        if k == "numeric_drift": return f"<div class='svg'>{r.get('svg','')}</div>"
        if k == "copy_paste_friction" and r.get("pending_rows"):
            rows = r["pending_rows"]; cols = [c for c in rows[0] if c != "_doc"]
            return "<table class='pv'><tr>" + "".join(f"<td><b>{c}</b></td>" for c in cols) + "</tr>" + "".join("<tr>" + "".join(f"<td>{html.escape(str(x.get(c)))}</td>" for c in cols) + "</tr>" for x in rows) + "</table>"
        if k == "price_change" and r.get("artifacts"): return xl_table(r["artifacts"][0], 8)
        if k in ("repeated_lookup", "deadline") and r.get("artifacts"):
            x = next((a for a in r["artifacts"] if a.endswith(".xlsx")), None)
            return xl_table(x, 7) if x else ""
        if k == "duplicate_charge" and r.get("artifacts"):
            return f"<pre class='draft'>{html.escape(Path(r['artifacts'][0]).read_text(encoding='utf-8'))}</pre><div class='more'>草稿，没有发送。要不要发、怎么发由你决定。</div>"
    except Exception as ex:
        return f"<div class='more'>预览失败：{html.escape(str(ex))}</div>"
    return ""

CSS = """body{font-family:'Noto Sans CJK SC','PingFang SC','Microsoft YaHei',sans-serif;background:#f4f5f7;margin:0;color:#1f2937}
.wrap{max-width:860px;margin:0 auto;padding:28px 20px 60px}
.hd{display:flex;align-items:center;gap:14px;margin-bottom:6px}.logo{width:40px;height:40px;border-radius:50%;border:4px solid #111827;position:relative}
.logo:after{content:'';position:absolute;width:10px;height:10px;border-radius:50%;background:#f59e0b;top:3px;right:3px}
h1{font-size:24px;margin:0}.sub{color:#6b7280;font-size:13px;margin:4px 0 22px}
.card{background:#fff;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.08);padding:18px 22px;margin-bottom:18px;border-left:5px solid #3b82f6}
.card.u0{border-left-color:#ef4444}.card.u1{border-left-color:#f59e0b}.card.u2{border-left-color:#9ca3af}
.meta{font-size:12px;color:#6b7280;display:flex;gap:8px;align-items:center;margin-bottom:6px}.tag{padding:2px 8px;border-radius:99px;background:#eef2ff;color:#3730a3}
.ok{background:#dcfce7;color:#166534}.dr{background:#fef3c7;color:#92400e}.hi{background:#fee2e2;color:#991b1b}
.card h2{font-size:18px;margin:4px 0 10px}.sec{margin:8px 0;line-height:1.65;font-size:14.5px}.sec b{color:#374151;display:inline-block;min-width:76px}
.ev{font-size:12.5px;color:#4b5563;background:#f9fafb;border-radius:8px;padding:8px 12px;margin:6px 0}.ev li{margin:2px 0}
table.pv{border-collapse:collapse;font-size:12px;margin:8px 0}table.pv td{border:1px solid #e5e7eb;padding:3px 7px}
.more{font-size:12px;color:#6b7280}.files a{font-size:12.5px;margin-right:12px}.btns{margin-top:12px}.btns span{display:inline-block;padding:6px 14px;border-radius:8px;margin-right:8px;font-size:13.5px;background:#f3f4f6;border:1px solid #e5e7eb}
.btns span:first-child{background:#111827;color:#fff;border-color:#111827}pre.draft{white-space:pre-wrap;background:#fffbeb;padding:10px;border-radius:8px;font-size:12.5px}
.svg{max-width:560px}.drawer{background:#fff;border-radius:14px;padding:14px 22px;font-size:13px;color:#4b5563}.drawer li{margin:4px 0}
.small{font-size:12px;color:#9ca3af;margin-top:24px}h3{font-size:15px;margin:26px 0 10px;color:#374151}"""

def render(summary, run_dir, out_dir=None, title_note=None):
    out_dir = Path(out_dir or run_dir); out_dir.mkdir(parents=True, exist_ok=True)
    fmap = {f["id"]: f for f in summary["findings"]}; res = summary["results"]; judge = summary["judge"]
    ids = order(summary); main, rest = ids[:5], ids[5:]
    prep = out_dir / "prepared"; prep.mkdir(exist_ok=True)
    src = summary.get("source") or {}
    now = str(summary.get("now") or "")[:10]
    if src.get("dataset"):
        who = f"真实开源数据 {src.get('dataset')}（许可 {src.get('license','?')}）"
        if src.get("participant"): who += f" · 参与者 {src['participant']}"
        banner = f"真实数据实测 · {who} · 模型：{summary['model']}"
        heading = f"已办清单 · 真实数据 · {now}"
    else:
        banner = f"演示：已导入 林晓雨（化学研二，模拟人物）过去 4 周的电脑使用记录 · 模型：{summary['model']}"
        heading = "已办清单 · 9月25日 周五 早上"
    md = [f"# OpenLookout {heading}\n", f"> {banner}\n"]
    H = [f"<!doctype html><html><head><meta charset='utf-8'><title>OpenLookout 已办清单</title><style>{CSS}</style></head><body><div class='wrap'>",
         f"<div class='hd'><div class='logo'></div><div><h1>{heading}</h1></div></div>",
         f"<div class='sub'>OpenLookout 瞭望手 · {banner} · 今天有 {len(main)} 件事需要你点一下"
         + (f" · {title_note}" if title_note else "") + "</div>"]
    def card_html(i, idx):
        f = fmap[i]; r = res[i]; c = summary["cards"][i]; s = r.get("slots", {}); u = URG.get(judge.get(i, {}).get("urgency"), 2)
        d = prep / i; d.mkdir(exist_ok=True); links = []
        for a in r.get("artifacts", []):
            if a and Path(a).exists():
                shutil.copy(a, d / Path(a).name); links.append(f"<a href='prepared/{i}/{html.escape(Path(a).name)}'>📄 {html.escape(Path(a).name)}</a>")
        st = "<span class='tag ok'>✓ 已在你的真实文件上验证</span>" if r["status"] == "verified" else ("<span class='tag dr'>只是提醒</span>" if r["status"] == "reminder_only" else "<span class='tag dr'>草稿，验证没全过</span>")
        ev = "".join(f"<li>{html.escape(e)}</li>" for e in evidence(f, r))
        opts = [fill(o, s) for o in (c.get("options") or ["以后自动做", "只这一次", "不用"])]
        md.append(f"## {idx}. {fill(c.get('title'), s)}\n\n*{KIND_CN.get(f['kind'], f['kind'])} · 紧急度 {judge.get(i, {}).get('urgency')} · {'已验证' if r['status']=='verified' else r['status']}*\n\n"
                  f"**我注意到：** {fill(c.get('noticed'), s)}\n\n**我已经准备好：** {fill(c.get('prepared'), s)}\n\n**验证：** {fill(c.get('verified'), s)}\n\n"
                  f"**{fill(c.get('question'), s)}** " + " / ".join(f"[{o}]" for o in opts) + "\n\n证据：\n" + "\n".join(f"- {e}" for e in evidence(f, r)) +
                  ("\n\n文件：" + "、".join(f"`prepared/{i}/{Path(a).name}`" for a in r.get("artifacts", []) if a) if r.get("artifacts") else "") + "\n")
        return (f"<div class='card u{u}'><div class='meta'><span class='tag {'hi' if u==0 else ''}'>瞭望到一件事 · {KIND_CN.get(f['kind'], f['kind'])}</span>{st}</div>"
                f"<h2>{html.escape(fill(c.get('title'), s))}</h2>"
                f"<div class='sec'><b>我注意到</b>{html.escape(fill(c.get('noticed'), s))}</div><ul class='ev'>{ev}</ul>"
                f"<div class='sec'><b>我已经准备好</b>{html.escape(fill(c.get('prepared'), s))}</div>{preview(f, r, '')}"
                f"<div class='files'>{''.join(links)}</div>"
                f"<div class='sec'><b>验证</b>{html.escape(fill(c.get('verified'), s))}</div>"
                f"<div class='sec'><b>{html.escape(fill(c.get('question'), s))}</b></div><div class='btns'>{''.join(f'<span>{html.escape(o)}</span>' for o in opts)}</div></div>")
    for n, i in enumerate(main, 1): H.append(card_html(i, n))
    if rest:
        H.append("<h3>不急，但也帮你准备好了</h3>"); md.append("\n---\n### 不急，但也帮你准备好了\n")
        for n, i in enumerate(rest, len(main) + 1): H.append(card_html(i, n))
    sil = summary["silent"]
    H.append(f"<h3>看到了，但没打扰你（{len(sil)}）</h3><div class='drawer'><ul>" + "".join(f"<li>{html.escape(x['desc'][:90])}<br><span class='more'>→ {html.escape(x['why'])}</span></li>" for x in sil) + "</ul></div>")
    md.append(f"\n---\n### 看到了，但没打扰你（{len(sil)}）\n" + "\n".join(f"- {x['desc']} → {x['why']}" for x in sil))
    tok = sum((x.get("prompt_tokens") or 0) + (x.get("completion_tokens") or 0) for x in summary["llm"])
    lat = sum(x["latency_s"] for x in summary["llm"])
    H.append(f"<div class='small'>本次：云端模型调用 {len(summary['llm'])} 次，共 {tok} tokens，模型耗时 {lat:.0f} 秒；发出去的只有脱敏描述和表格结构（runs/…/outbound/ 可逐字查看）。原始记录、文件内容、人名、金额都没有离开本机。所有动作都只生成了新文件，没有发送、提交、付款或删除任何东西。</div></div></body></html>")
    (out_dir / "inbox.html").write_text("\n".join(H), encoding="utf-8")
    (out_dir / "inbox.md").write_text("\n".join(md), encoding="utf-8")
