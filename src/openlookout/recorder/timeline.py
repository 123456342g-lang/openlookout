"""把 events.jsonl 渲染成「今天的时间线」静态页面（无截图）。
用法：python3 recorder/timeline.py [events.jsonl] [日期 YYYY-MM-DD] [输出.html]
"""
import html, json, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

src = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "out" / "events.jsonl")
evs = sorted((json.loads(l) for l in open(src, encoding="utf-8") if l.strip()), key=lambda e: e["ts"])
day = (sys.argv[2] if len(sys.argv) > 2 else "") or (evs[-1]["ts"][:10] if evs else datetime.now().strftime("%Y-%m-%d"))
out = Path(sys.argv[3] if len(sys.argv) > 3 else src.with_name(f"timeline-{day}.html"))
evs = [e for e in evs if e["ts"].startswith(day)]

apps = defaultdict(int)
for e in evs:
    if e["type"] == "focus": apps[e["app"]] += e.get("dur_s", 0)
total = sum(apps.values()) or 1
colors = ["#4f7cff", "#22b07d", "#f2a33a", "#e5566b", "#8a63d2", "#2bb3c0", "#9aa1ad"]
cmap = {a: colors[min(i, len(colors) - 1)] for i, (a, _) in enumerate(sorted(apps.items(), key=lambda x: -x[1]))}

def fmt(s):
    h, m = divmod(s // 60, 60); return f"{h} 小时 {m} 分" if h else f"{m} 分" if m else f"{s} 秒"
def desc(e):
    t, x = e["type"], html.escape
    if t == "focus": return f'在 <b>{x(e.get("title") or e["app"])}</b> 停留 {fmt(e.get("dur_s", 0))}' + (f' <span class=u>{x(e["url"])}</span>' if e.get("url") else "")
    if t == "file_open": return f'打开文件 <code>{x(e["path"])}</code>'
    if t == "file_save": return f'保存文件 <code>{x(e["path"])}</code>'
    if t == "clipboard": return f'从 <b>{x(e.get("src_title") or e.get("src_app") or "?")}</b> 复制 {e.get("len", 0)} 个字，粘到 <b>{x(e.get("dst_title") or e.get("dst_app") or "?")}</b>'
    if t == "form_edit": return f'在网页表单「{x(e.get("field_label", ""))}」里{"粘贴" if e.get("via") == "paste" else "输入"}'
    return x(t)
icons = {"focus": "🪟", "file_open": "📂", "file_save": "💾", "clipboard": "📋", "form_edit": "📝"}

bar = "".join(f'<div style="flex:{s};background:{cmap[a]}" title="{html.escape(a)} {fmt(s)}"></div>' for a, s in sorted(apps.items(), key=lambda x: -x[1]))
legend = "".join(f'<span><i style="background:{cmap[a]}"></i>{html.escape(a)} · {fmt(s)} · {round(100*s/total)}%</span>' for a, s in sorted(apps.items(), key=lambda x: -x[1]))
rows = "".join(f'<li class={e["type"]}><time>{e["ts"][11:16]}</time><span>{icons.get(e["type"], "•")}</span><div>{desc(e)}</div></li>'
               for e in evs if not (e["type"] == "focus" and e.get("dur_s", 0) < 5))
counts = defaultdict(int)
for e in evs: counts[e["type"]] += 1
out.write_text(f"""<!doctype html><meta charset=utf-8><title>今天的时间线 {day}</title>
<style>body{{font:15px/1.6 system-ui,"Noto Sans CJK SC",sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#1d2330}}
h1{{font-size:22px;margin:0}}.sub{{color:#6b7280;margin-bottom:18px}}.bar{{display:flex;height:16px;border-radius:8px;overflow:hidden;margin:10px 0}}
.lg span{{display:inline-block;margin:0 14px 6px 0;font-size:13px;color:#4b5563}}.lg i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}}
ul{{list-style:none;padding:0;margin-top:22px}}li{{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid #eef0f3}}time{{color:#9aa1ad;width:44px;flex:none;font-variant-numeric:tabular-nums}}
li.clipboard{{background:#fff8e6}}code{{font-size:13px;background:#f3f4f6;padding:1px 5px;border-radius:4px}}.u{{color:#9aa1ad;font-size:12px}}</style>
<h1>今天的时间线 · {day}</h1><div class=sub>共 {len(evs)} 条记录：窗口 {counts['focus']}、文件 {counts['file_open']+counts['file_save']}、复制粘贴 {counts['clipboard']}、表单 {counts['form_edit']}。没有截图，复制的原文不在这里。</div>
<div class=bar>{bar}</div><div class=lg>{legend}</div><ul>{rows}</ul>""", encoding="utf-8")
print(out)
