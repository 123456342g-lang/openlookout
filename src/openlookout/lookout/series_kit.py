"""系列任务（实验1…实验N）的成品：每期交付文件清单 + 一个“开新一期”的小脚本（默认只演示、不动文件）。
验证：用历史路径在沙箱里建一份只有文件名的镜像，让脚本对每一期“从任务书开新一期”，看它推出的编号/标题
和你当时真正交的报告文件名是否对得上；再确认演示模式不写任何文件、执行模式只新建、不覆盖。"""
import csv, json, re, shutil, subprocess, sys
from pathlib import Path, PurePosixPath

SCAFFOLD = r'''#!/usr/bin/env python3
"""开新一期：python new_episode.py <这一期的任务书.pdf> [--template 模板.doc] [--prefix 第1组-] [--do]
默认只打印将要做什么；加 --do 才会新建文件夹、复制模板（已存在的文件绝不覆盖）。只用标准库，Windows/Linux 都能跑。
由 OpenLookout 生成。"""
import argparse, re, shutil, sys
from pathlib import Path
CN = dict(zip("一二三四五六七八九十", range(1, 11)))
def parse(brief, word):
    stem = Path(brief).stem
    m = re.search(re.escape(word) + r"\s*(\d+|[一二三四五六七八九十]+)", stem)
    if not m: sys.exit(f"任务书名字里找不到“{word}+编号”：{stem}")
    n = int(m.group(1)) if m.group(1).isdigit() else CN.get(m.group(1))
    title = re.sub(r"^[\s_\-—:：]+", "", stem[m.end():]).strip()
    return n, title
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("brief"); ap.add_argument("--word", default=__WORD__); ap.add_argument("--template", default=__TEMPLATE__)
    ap.add_argument("--prefix", default=__PREFIX__); ap.add_argument("--root", default=None, help="放各期文件夹的目录，默认是任务书所在目录的上一级（若任务书已在编号文件夹里）")
    ap.add_argument("--extra-dirs", default=__EXTRA__); ap.add_argument("--do", action="store_true")
    a = ap.parse_args()
    brief = Path(a.brief); n, title = parse(brief, a.word)
    here = brief.parent
    root = Path(a.root) if a.root else (here.parent if re.fullmatch(re.escape(a.word) + r"\s*\d+", here.name) else here)
    folder = root / f"{a.word}{n}"
    tpl = Path(a.template) if a.template else None
    ext = tpl.suffix if tpl else ".docx"
    report = folder / f"{a.prefix}{a.word}{n}_{title}{ext}"
    plan = [("建文件夹", folder)] + [("建文件夹", folder / d) for d in a.extra_dirs.split(",") if d] + \
           ([("复制模板", report)] if tpl else [("（没给模板，只建文件夹）", report)])
    for what, p in plan: print(f"{what}: {p}" + ("  （已存在，跳过）" if p.exists() else ""))
    if not a.do: print("演示模式：什么都没改。确认无误后加 --do。"); return
    for what, p in plan:
        if p.exists(): continue
        if what == "建文件夹": p.mkdir(parents=True)
        elif what == "复制模板":
            if not tpl.exists(): sys.exit(f"模板不存在：{tpl}")
            shutil.copyfile(tpl, p)
    print("完成。")
if __name__ == "__main__":
    main()
'''

def _cn_title(stem, word):
    m = re.search(re.escape(word) + r"\s*(\d+|[一二三四五六七八九十]+)", stem)
    return re.sub(r"^[\s_\-—:：]+", "", stem[m.end():]).strip() if m else None

def build(f, outdir):
    L = f["local"]; outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    word = L["prefix"]
    # 1. 清单
    idx = outdir / "各期交付文件清单.csv"
    with open(idx, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh); w.writerow(["期", "文件", "最后修改", "大小(KB)", "标记"])
        for n in L["numbers"]:
            items = L["items"].get(n) or L["items"].get(str(n)) or []
            newest = items[-1]["path"] if items else None
            for it in items:
                twins = [x for x in items if x is not it and x["size"] and x["size"] == it["size"]]
                mark = ("最新（按修改时间）" if it["path"] == newest else "") + ("；与 " + "、".join(PurePosixPath(x["path"]).name for x in twins) + " 大小完全相同（多半是另存的同一份）" if twins else "")
                w.writerow([n, it["path"], it["saved"], (it["size"] or 0) // 1024, mark.strip("；")])
    # 2. 脚本：模板 = 历史里被反复打开、名字里带“模板/template”的文件；前缀 = 最近一期报告的写法
    tpl = None
    for n in L["numbers"]:
        for it in (L["items"].get(n) or L["items"].get(str(n)) or []):
            if re.search(r"模板|template", PurePosixPath(it["path"]).name, re.I): tpl = it["path"]
    last_items = [it for it in (L["items"].get(L["numbers"][-1]) or L["items"].get(str(L["numbers"][-1])) or []) if not re.search(r"模板|template", it["path"], re.I)]
    prefix = ""
    if last_items:
        stem = PurePosixPath(last_items[-1]["path"]).stem
        m = re.search(re.escape(word) + r"\s*\d+", stem); prefix = stem[:m.start()] if m else ""
    extra = ",".join(sorted({p for n in L["numbers"] for it in (L["items"].get(n) or L["items"].get(str(n)) or [])
                             for p in [PurePosixPath(it["path"]).parent.name] if p != f"{word}{n}" and not re.search(r"\d", p)} & {"截图"}))
    src = SCAFFOLD.replace("__WORD__", repr(word)).replace("__TEMPLATE__", repr(tpl.replace("/", "\\") if tpl and re.match(r"^[A-Za-z]:/", tpl) else tpl)) \
                  .replace("__PREFIX__", repr(prefix)).replace("__EXTRA__", repr(extra))
    script = outdir / "new_episode.py"; script.write_text(src, encoding="utf-8")
    return {"index": str(idx), "script": str(script), "template": tpl, "prefix": prefix, "extra_dirs": extra}

def verify(f, built, sandbox):
    """在沙箱里用历史文件名建镜像（空文件），逐期回放。"""
    L = f["local"]; word = L["prefix"]; sandbox = Path(sandbox)
    if sandbox.exists(): shutil.rmtree(sandbox)
    def mirror(p):
        q = sandbox / re.sub(r"^([A-Za-z]):/", r"\1_/", p); q.parent.mkdir(parents=True, exist_ok=True); q.touch(); return q
    allp = {it["path"] for v in L["items"].values() for it in v} | set(L["briefs"].values())
    for p in allp: mirror(p)
    tpl = built["template"]; tpl_m = str(sandbox / re.sub(r"^([A-Za-z]):/", r"\1_/", tpl)) if tpl else None
    rows, ok = [], 0
    for n in L["numbers"]:
        brief = L["briefs"].get(n) or L["briefs"].get(str(n))
        items = [it for it in (L["items"].get(n) or L["items"].get(str(n)) or []) if not re.search(r"模板|template", it["path"], re.I)]
        if not brief or not items: rows.append({"n": n, "skipped": "没有任务书或没有报告"}); continue
        bq = sandbox / re.sub(r"^([A-Za-z]):/", r"\1_/", brief)
        args = [sys.executable, built["script"], str(bq)] + (["--template", tpl_m] if tpl_m else [])
        before = sorted(str(p) for p in sandbox.rglob("*"))
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        after = sorted(str(p) for p in sandbox.rglob("*"))
        m = re.search(r"复制模板: (.+)", r.stdout) or re.search(r"只建文件夹）: (.+)", r.stdout)
        planned = PurePosixPath(m.group(1).split("  （")[0]).name if m else ""
        title = _cn_title(PurePosixPath(brief).stem, word)
        real_titles = [_cn_title(PurePosixPath(it["path"]).stem, word) for it in items]
        hit = bool(title) and any(t and (t == title or t.startswith(title)) for t in real_titles) and f"{word}{n}_" in planned
        ok += hit
        rows.append({"n": n, "planned": planned, "title_from_brief": title, "title_in_real_reports": hit, "dry_run_wrote_nothing": before == after})
    # 执行模式：用最后一期的任务书，在一个全新的空目录里试一次
    tmp = sandbox / "_do_test"; tmp.mkdir()
    last_brief = L["briefs"].get(L["numbers"][-1]) or L["briefs"].get(str(L["numbers"][-1]))
    created = []
    if last_brief:
        b = tmp / PurePosixPath(last_brief).name; b.touch()
        args = [sys.executable, built["script"], str(b), "--root", str(tmp / "out"), "--do"] + (["--template", tpl_m] if tpl_m else [])
        subprocess.run(args, capture_output=True, text=True, timeout=30)
        created = sorted(str(p.relative_to(tmp)) for p in (tmp / "out").rglob("*")) if (tmp / "out").exists() else []
        again = subprocess.run(args, capture_output=True, text=True, timeout=30).stdout   # 再跑一次：不能覆盖
    checked = [r for r in rows if "planned" in r]
    return {"episodes_replayed": len(checked), "title_and_number_match": ok, "dry_run_never_writes": all(r["dry_run_wrote_nothing"] for r in checked),
            "do_mode_created": len(created), "rerun_skips_existing": ("已存在，跳过" in again) if last_brief else None, "rows": rows}
