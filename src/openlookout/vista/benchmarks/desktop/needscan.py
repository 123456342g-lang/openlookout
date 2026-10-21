"""从整机操作历史里发现问题/机会 —— 长期感知的「找」那一半。

设计约束（来自 09a/09b 两份调研）：
- 09a：UI 日志必须先建「动作字母表」把 object 降维（扩展名/父目录/域名），
  否则精确子序列匹配的支持度恒为 1，退化成罗列历史。这里只做计数级聚合，
  不上频繁子序列，先把假阳性压住。
- 09a 批判性证据：Malone 1983 / Bergman & Whittaker 2016 / Dinneen & Frissen 2020
  都指出「杂乱可能是有功能的」「从文件集合反推用户的最小预测力」——所以这里
  只输出**可核对的计数事实**，不输出「你有问题」这种判断。
- 09b：分档必须由**确定性代码**裁定，不能由模型自报置信度（三难 2605.25739）。
  所以 tier_of() 只吃四个可枚举输入，不读模型输出。
- 09b：POLAR 把可撤销性从「事后能撤」提前到「事前能判」——每档都带证据物。
"""
from __future__ import annotations

import json
import re
import time
import zipfile
from collections import defaultdict
from pathlib import Path

from sprite.config import sprite_home

DEFAULT_EVENTS = sprite_home() / "events.jsonl"
DEFAULT_EVENTS_SET = (DEFAULT_EVENTS, sprite_home() / "backfill" / "events.jsonl")

# R7 作业/实验用的词表。中英分开，避免「lab」误命中「label」之类。
HOMEWORK_WORDS = ("实验", "作业", "课程", "考勤", "实习", "大作业", "期末", "论文", "小组",
                  "实验报告", "习题", "作业本", "homework", "assignment", "coursework",
                  "/lab", "lab_", "实验1", "实验2", "实验3")
# 「要求/模板」类：说明要交什么；「成品」类：说明已经交了。
HOMEWORK_ASK = ("要求", "模板", "指导", "任务书", "说明", "题目", "实验指导", "格式",
                "参考格式", "readme")


def _stem(name: str) -> str:
    """去掉扩展名再匹配——否则「作业一.docx」会因为扩展名里的 doc 被误判成要求文件。"""
    return name.rsplit(".", 1)[0].lower()
HOMEWORK_OUT = ("报告", "答案", "成品", "提交", "完成", "结果", "report", "answer", "submit")

_NOISE_SEG = ("wxwork", "tencent files", "code cache", "service worker", "cachestorage",
              "cefcache", "leveldb", "gpucache", "crashpad", "cache", "logs", "log",
              "node_modules", ".git", "__pycache__", "appdata", "temp", "tmp",
              "shadercache", "dawncache", "grshadercache")
_NOISE_NAME = {"log", "log.old", "temp-index", "the-real-index", "index", "lock",
               "config.cfg", "kv.db", "kv.db-wal", "kv.db-shm", "preferences",
               "local state", "history", "history-journal"}
_DOC_EXT = {".md", ".txt", ".doc", ".docx", ".pdf", ".xls", ".xlsx", ".csv", ".ppt",
            ".pptx", ".py", ".js", ".ts", ".json", ".exe", ".zip", ".msi", ".7z",
            ".rar", ".png", ".jpg", ".jpeg", ".html", ".yml", ".yaml", ".toml",
            ".cfg", ".ini", ".bat", ".ps1", ".sh", ".sql", ".ipynb"}
_PKG_EXT = {".exe", ".msi", ".zip", ".7z", ".rar", ".dmg", ".apk"}


def is_user_file(path: str) -> bool:
    if not path:
        return False
    low = path.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    if name in _NOISE_NAME:
        return False
    if any(seg in low for seg in _NOISE_SEG):
        return False
    if "." not in name:
        return False
    return ("." + name.rsplit(".", 1)[-1]) in _DOC_EXT


def tier_of(*, reversible: bool, outward: bool, blast: int, has_preview: bool) -> tuple[str, str]:
    """确定性分档（GAIE）：只吃四个可枚举输入，模型无权改判。

    T0 默默做 / T1 做完汇报 / T2 必须先问
    """
    if not reversible or outward or blast >= 50:
        return "T2", "不可撤销或对外可见或影响面≥50，必须先问"
    if blast >= 5 or not has_preview:
        return "T1", "影响面≥5 或没有预览，做完汇报且必须留证据物"
    return "T0", "局部、可撤销、有预览、影响面小，可默默做并留证据物"


def load(path: Path, *, days: float, now: float | None = None) -> list[dict]:
    now = now or time.time()
    cutoff = now - days * 86400.0
    out = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            if not raw.startswith("{"):
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            moment = row.get("_ts") or row.get("ts")
            if isinstance(moment, str):
                try:
                    from datetime import datetime
                    moment = datetime.fromisoformat(moment).timestamp()
                except ValueError:
                    continue
            if not isinstance(moment, (int, float)) or moment < cutoff or moment > now + 300:
                continue
            row["_t"] = float(moment)
            out.append(row)
    out.sort(key=lambda item: item["_t"])
    return out


TEXT_EXT = {".md", ".txt", ".csv", ".json", ".py", ".java", ".c", ".cpp", ".h",
            ".sql", ".html", ".htm", ".log", ".ini", ".yml", ".yaml", ".sh", ".bat"}
OFFICE_EXT = {".docx", ".xlsx", ".pptx"}


def resolve_path(p: str) -> Path | None:
    """把账本里的路径还原成真实路径。

    记录器会把 `C:\\Users\\q\\...` 缩成 `q/...`（隐私处理），所以账本里的相对路径
    不是相对当前目录，而是相对「某个用户主目录」。这里逐个候选试，试不出来返回 None。
    """
    raw = Path(p)
    cands = [raw]
    if not raw.is_absolute():
        parts = p.replace("\\", "/").split("/")
        if len(parts) >= 2:
            cands.append(Path(f"C:/Users/{parts[0]}") / Path(*parts[1:]))
        cands.append(Path("C:/") / Path(*parts))
        cands.append(Path("E:/") / Path(*parts))
    for cand in cands:
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def _soffice_text(path: Path, limit: int) -> str:
    """.doc/.xls/.ppt（老的二进制 Office）用本机 LibreOffice 无头转文本。

    这台机器上装了 `C:\\Program Files\\LibreOffice\\program\\soffice.exe`，
    所以「读不了」不是事实，是没试。
    """
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("soffice") or r"C:\Program Files\LibreOffice\program\soffice.exe"
    if not Path(exe).exists():
        return ""
    with tempfile.TemporaryDirectory() as td:
        try:
            subprocess.run([exe, "--headless", "--norestore", "--convert-to", "txt:Text",
                            "--outdir", td, str(path)],
                           timeout=90, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return ""
        out = Path(td) / (path.stem + ".txt")
        if not out.is_file():
            found = sorted(Path(td).glob("*.txt"))
            if not found:
                return ""
            out = found[0]
        for enc in ("utf-8", "gbk"):
            try:
                return out.read_text(encoding=enc)[:limit]
            except (UnicodeDecodeError, OSError):
                continue
        return out.read_text(encoding="utf-8", errors="ignore")[:limit]


def _pdf_text(path: Path, limit: int) -> str:
    try:
        import fitz  # PyMuPDF
        with fitz.open(str(path)) as doc:
            return "\n".join(page.get_text() for page in doc)[:limit]
    except Exception:
        pass
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)[:limit]
    except Exception:
        return ""


def _docx_text(path: Path, limit: int) -> str:
    try:
        import docx  # python-docx
        doc = docx.Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        text = "\n".join(x for x in parts if x and x.strip())
        if text.strip():
            return text[:limit]
    except Exception:
        pass
    # 退回 zip+XML：不依赖第三方库，xlsx/pptx 也走这条
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist()
                     if n.endswith(".xml") and ("document" in n or "sharedStrings" in n
                                                or "sheet" in n or "slide" in n)]
            chunks = []
            for name in names[:8]:
                xml = z.read(name).decode("utf-8", errors="ignore")
                xml = re.sub(r"</w:p>|</a:p>|</row>", "\n", xml)
                chunks.append(re.sub(r"<[^>]+>", "", xml))
        body = re.sub(r"[ \t]+\n", "\n", "\n".join(chunks))
        return re.sub(r"\n{2,}", "\n", body).strip()[:limit]
    except (OSError, zipfile.BadZipFile, KeyError):
        return ""


def read_text(path: str, limit: int = 4000) -> str:
    """把文件的正文读出来。**不要凭扩展名说自己读不了。**

    本机已具备：python-docx（.docx/.xlsx/.pptx）、PyMuPDF + pypdf（.pdf）、
    LibreOffice 无头转换（.doc/.xls/.ppt）。只有这些全都失败才返回空串。
    """
    p = resolve_path(path)
    if p is None:
        return ""
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _pdf_text(p, limit)
    if ext in (".docx", ".xlsx", ".pptx"):
        return _docx_text(p, limit)
    if ext in (".doc", ".xls", ".ppt", ".rtf"):
        return _soffice_text(p, limit)
    if ext not in TEXT_EXT:
        return ""
    try:
        raw = p.read_bytes()[:600_000]
    except OSError:
        return ""
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return raw.decode(enc)[:limit]
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")[:limit]


def homework(days: float = 30.0, max_chars: int = 4000,
             now: float | None = None) -> dict:
    """R7 的「可动手」版本：找出作业/实验目录，并把要求文件的正文读出来。

    只读：不写任何文件。返回的是「要交什么」的原文 + 目录里已有什么，
    让大脑据此在**同一目录新增**一份草稿，而不是替换用户任何现有文件。
    """
    now = now if now is not None else time.time()
    ev: list[dict] = []
    for one in DEFAULT_EVENTS_SET:
        ev.extend(load(one, days=days, now=now))
    dirs: dict[str, dict] = {}
    hints_all: list[str] = []
    for row in ev:
        # 作业不一定留下文件：用户可能只是打开课程页/看了指导，操作流里只有窗口标题。
        # 所以标题也要当证据——这正是「只找文件」会漏掉的那一半。
        title = str(row.get("title") or "")
        if title and any(w in title.lower() for w in HOMEWORK_WORDS):
            stamp = time.strftime("%m-%d %H:%M", time.localtime(row["_t"]))
            hint = f"{stamp}  {row.get('app') or '?'}  「{title[:60]}」"
            if hint not in hints_all:
                hints_all.append(hint)
        p = str(row.get("path") or "").replace("\\", "/")
        if not p or not is_user_file(p):
            continue
        if not any(w in p.lower() for w in HOMEWORK_WORDS):
            continue
        folder, name = (p.rsplit("/", 1) + [""])[:2] if "/" in p else ("", p)
        slot = dirs.setdefault(folder, {"files": {}, "last": 0.0})
        slot["files"][name] = max(slot["files"].get(name, 0.0), row["_t"])
        slot["last"] = max(slot["last"], row["_t"])
    hints = []
    for hint in hints_all[:6]:
        hints.append(hint)
    out = []
    for folder, slot in sorted(dirs.items(), key=lambda kv: -kv[1]["last"])[:6]:
        names = sorted(slot["files"], key=lambda n: -slot["files"][n])
        asks = [n for n in names if any(w in _stem(n) for w in HOMEWORK_ASK)]
        outs = [n for n in names
                if any(w in _stem(n) for w in HOMEWORK_OUT)
                and not any(w in _stem(n) for w in HOMEWORK_ASK)]
        entry = {"folder": folder or ".", "files": names[:8],
                 "last_seen": time.strftime("%m-%d %H:%M", time.localtime(slot["last"])),
                 "has_requirement": bool(asks), "already_delivered": bool(outs),
                 "requirement_files": asks[:3], "unreadable": [],
                 "existing_deliverables": outs[:5]}
        if folder:
            for name in asks[:3]:
                blob = read_text(f"{folder}/{name}", max_chars)
                if blob:
                    entry.setdefault("requirement_text", {})[name] = blob
                else:
                    entry["unreadable"].append(name)
        out.append(entry)
    return {"ok": True, "folders": out, "days": days, "task_hints": hints}


def scan(path: Path | None = None, *, days: float = 120.0, limit: int = 8,
         now: float | None = None) -> dict:
    paths = [path] if path is not None else list(DEFAULT_EVENTS_SET)
    ev: list[dict] = []
    for one in paths:
        ev.extend(load(one, days=days, now=now))
    ev.sort(key=lambda item: item["_t"])
    findings: list[dict] = []

    # R1 下载后从未打开的安装包/压缩包
    created: dict[str, dict] = {}
    for row in ev:
        joins = [str(v) for v in (row.get("path"), row.get("file")) if v]
        if str(row.get("type")) in ("file_create", "file_save", "file_open"):
            for joined in joins:
                if str(row.get("type")) == "file_create":
                    created.setdefault(joined, row)
    opened = {str(row.get("path")) for row in ev
              if str(row.get("type")) in ("file_open", "file_save")}
    idle = [(p, r) for p, r in created.items()
            if p not in opened and is_user_file(p)]
    idle.sort(key=lambda item: -(item[1].get("size") or 0))
    if idle:
        total = sum((r.get("size") or 0) for _, r in idle)
        findings.append({
            "id": "R1-idle-downloads",
            "kind": "问题",
            "what": f"{len(idle)} 个下载/新建的文件此后再没被打开或保存过，共约 {total/1e6:.0f} MB",
            "count": len(idle),
            "evidence": [f"{p} ← {r.get('app') or '?'} {(r.get('size') or 0)/1e6:.1f}MB"
                         for p, r in idle[:5]],
            "proposed_action": "只把最近 7 天的、看起来是当时在找的安装包/模板列出来说一句；超过 30 天的不提",
            "reversible": True, "outward": False, "blast": 1, "has_preview": True,
        })

    # R2 反复打开的文件（跨天）
    opens: dict[str, list[float]] = defaultdict(list)
    saves: dict[str, list[float]] = defaultdict(list)
    for row in ev:
        p = str(row.get("path") or "")
        if not is_user_file(p):
            continue
        if row.get("type") == "file_open":
            opens[p].append(row["_t"])
        elif row.get("type") == "file_save":
            saves[p].append(row["_t"])
    revisit = [(p, t) for p, t in opens.items()
               if len(t) >= 3 and (max(t) - min(t)) >= 86400]
    revisit.sort(key=lambda item: -len(item[1]))
    if revisit:
        findings.append({
            "id": "R2-revisit-loop",
            "kind": "机会",
            "what": f"{len(revisit)} 个文件被跨天反复打开（最多的开了 {len(revisit[0][1])} 次）",
            "count": len(revisit),
            "evidence": [f"{p}  {len(t)} 次  {time.strftime('%m-%d', time.localtime(min(t)))}"
                         f"→{time.strftime('%m-%d', time.localtime(max(t)))}"
                         for p, t in revisit[:5]],
            "proposed_action": "对反复打开却长期没有下一步的文件，主动把「上次看到哪、还差什么」写成一页放在旁边（新文件，可删）",
            "reversible": True, "outward": False, "blast": 1, "has_preview": True,
        })

    # R3 保存次数异常多的文件（长期在手，是最好的锚点）
    churn = [(p, t) for p, t in saves.items() if len(t) >= 5]
    churn.sort(key=lambda item: -len(item[1]))
    if churn:
        findings.append({
            "id": "R3-save-churn",
            "kind": "机会",
            "what": f"{len(churn)} 个文件保存 ≥5 次（最多 {len(churn[0][1])} 次）",
            "count": len(churn),
            "evidence": [f"{p}  {len(t)} 次" for p, t in churn[:5]],
            "proposed_action": "只记录不打扰：这些是「长期在手」的文件，是判断用户当下在做什么的最好锚点",
            "reversible": True, "outward": False, "blast": 0, "has_preview": True,
        })

    # R4 同名文件散落多个目录
    by_name: dict[str, set] = defaultdict(set)
    for row in ev:
        p = str(row.get("path") or "").replace("\\", "/")
        if is_user_file(p):
            by_name[p.rsplit("/", 1)[-1].lower()].add(p.rsplit("/", 1)[0])
    scattered = [(n, d) for n, d in by_name.items() if len(d) >= 3]
    scattered.sort(key=lambda item: -len(item[1]))
    if scattered:
        findings.append({
            "id": "R4-scattered-same-name",
            "kind": "问题",
            "what": f"{len(scattered)} 个文件名散落在 ≥3 个目录",
            "count": len(scattered),
            "evidence": [f"{n}  {len(d)} 处: " + " | ".join(sorted(d)[:3])
                         for n, d in scattered[:3]],
            "proposed_action": "指出「同一份东西有几个版本」并列出各自最后改动时间，让人决定留哪个；绝不自动合并或删除",
            "reversible": True, "outward": False, "blast": 0, "has_preview": True,
        })

    # R5 30 秒内来回切换（最不该打断的时刻）
    pingpong: dict[tuple, int] = defaultdict(int)
    prev_app, prev_t = "", 0.0
    for row in ev:
        if row.get("type") != "focus":
            continue
        app = str(row.get("app") or "").strip()
        if not app:
            continue
        if prev_app and app != prev_app and row["_t"] - prev_t <= 30:
            pingpong[tuple(sorted((prev_app, app)))] += 1
        prev_app, prev_t = app, row["_t"]
    pairs = sorted(pingpong.items(), key=lambda item: -item[1])[:5]
    if pairs:
        findings.append({
            "id": "R5-window-pingpong",
            "kind": "问题",
            "what": f"{len(pingpong)} 组应用在 30 秒内来回切换",
            "count": len(pingpong),
            "evidence": [f"{a} ↔ {b}  {n} 次" for (a, b), n in pairs],
            "proposed_action": "这是「手在两边搬东西」的信号；先只记录，作为触发 timing 的边——这种时刻最不该打断",
            "reversible": True, "outward": False, "blast": 0, "has_preview": True,
        })

    # R6 剪贴板搬运路线
    routes: dict[tuple, int] = defaultdict(int)
    for row in ev:
        if row.get("type") == "clipboard":
            routes[(str(row.get("src_app") or "?"), str(row.get("dst_app") or "?"))] += 1
    top_routes = sorted(routes.items(), key=lambda item: -item[1])[:5]
    if top_routes:
        findings.append({
            "id": "R6-clipboard-routes",
            "kind": "机会",
            "what": f"{sum(routes.values())} 次剪贴板搬运，集中在 {len(routes)} 条路线上",
            "count": sum(routes.values()),
            "evidence": [f"{a} → {b}  {n} 次" for (a, b), n in top_routes],
            "proposed_action": "对最高频的那条路线，主动写一个「一键搬运」小脚本放在桌面（新文件），不替换用户任何现有习惯",
            "reversible": True, "outward": False, "blast": 1, "has_preview": True,
        })

    # R7 作业/实验：找到「用户需要完成的东西」并标出缺口
    hw_dirs: dict[str, dict] = {}
    for row in ev:
        p = str(row.get("path") or "").replace("\\", "/")
        if not p or not is_user_file(p):
            continue
        low = p.lower()
        if not any(w in low for w in HOMEWORK_WORDS):
            continue
        folder, name = (p.rsplit("/", 1) + [""])[:2] if "/" in p else ("", p)
        slot = hw_dirs.setdefault(folder, {"files": {}, "last": 0.0})
        slot["files"][name] = max(slot["files"].get(name, 0.0), row["_t"])
        slot["last"] = max(slot["last"], row["_t"])
    if hw_dirs:
        ranked = sorted(hw_dirs.items(), key=lambda kv: -kv[1]["last"])[:6]
        evidence, gaps = [], []
        for folder, slot in ranked:
            names = sorted(slot["files"], key=lambda n: -slot["files"][n])
            stamp = time.strftime("%m-%d %H:%M", time.localtime(slot["last"]))
            evidence.append(f"{stamp}  {folder or '.'}  →  " + "、".join(names[:4]))
            has_ask = any(any(w in _stem(n) for w in HOMEWORK_ASK) for n in names)
            has_out = any(any(w in _stem(n) for w in HOMEWORK_OUT) for n in names)
            if has_ask and not has_out:
                gaps.append(f"{folder or '.'}：有要求/模板，没看到成品")
        findings.append({
            "id": "R7-homework",
            "kind": "问题",
            "what": f"{sum(len(s['files']) for s in hw_dirs.values())} 个作业/实验相关文件，分布在 {len(hw_dirs)} 个目录",
            "count": sum(len(s["files"]) for s in hw_dirs.values()),
            "evidence": evidence + ([f"缺口：{g}" for g in gaps[:4]] if gaps else []),
            "proposed_action": "读该目录里的要求/模板文件，把「要交什么」抽出来；先只在同目录新增一个草稿文件（不动原文件），再把草稿路径汇报给用户",
            "reversible": True, "outward": False, "blast": 1, "has_preview": True,
        })

    for item in findings:
        tier, why = tier_of(reversible=item["reversible"], outward=item["outward"],
                            blast=item["blast"], has_preview=item["has_preview"])
        item["tier"] = tier
        item["tier_why"] = why
    return {"events": len(ev), "span_days": days,
            "findings": findings[:limit]}


if __name__ == "__main__":
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVENTS
    report = scan(path)
    print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])
