"""行为 × 趋势交叉：在行为 finding 上挂已验证趋势，并按 kits 追加成品。

仍服从 V1：不是新闻卡；没有行为证据或没有可构建成品 → 不出。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from . import trends as T

TOOL_PAT = re.compile(
    r"(opencode|codex(?:\s*cli)?|ollama|langflow|cc[\s_-]?switch|claude(?:-?code)?)",
    re.I,
)
OL_PAT = re.compile(r"openlookout|瞭望手", re.I)


def detect_tool_stack_churn(evs, meta):
    """从历史里统计 AI 编程工具出现频次与跨天数 → 工具栈切换税。"""
    by = defaultdict(lambda: {"n": 0, "days": set(), "samples": []})
    for e in evs:
        blob = " ".join(str(e.get(k) or "") for k in ("title", "path", "url", "app"))
        for m in TOOL_PAT.finditer(blob):
            name = re.sub(r"[\s_-]+", "", m.group(1).lower())
            if name.startswith("claude"):
                name = "claude"
            if name.startswith("codex"):
                name = "codex"
            if name.startswith("cc"):
                name = "ccswitch"
            by[name]["n"] += 1
            day = (e.get("ts") or "")[:10]
            if day:
                by[name]["days"].add(day)
            if len(by[name]["samples"]) < 3:
                by[name]["samples"].append({"ts": e.get("ts"), "type": e.get("type")})
    if len(by) < 2:
        return []
    tools = sorted(by.items(), key=lambda x: -x[1]["n"])
    total = sum(v["n"] for _, v in tools)
    days_all = set().union(*(v["days"] for _, v in tools))
    if total < 20 or len(days_all) < 5:
        return []
    top = tools[:6]
    return [{
        "kind": "tool_stack_churn",
        "score": 18 + len(by) * 3 + min(20, total // 50),
        "local": {
            "tools": [{"name": n, "events": v["n"], "days": len(v["days"])} for n, v in top],
            "n_tools": len(by),
            "total_events": total,
            "span_days": len(days_all),
        },
        "facts": {
            "distinct_agents": len(by),
            "tool_events": total,
            "active_days": len(days_all),
            "top_tool_events": top[0][1]["n"],
            "top_tool_days": len(top[0][1]["days"]),
        },
    }]


def detect_openlookout_build(evs, meta):
    """用户在自己做 OpenLookout / 瞭望手相关文件。"""
    hits = []
    for e in evs:
        src = str(e.get("source") or "")
        if src.startswith("derived:git"):
            continue  # git 派生默认不计入，避免把分析机仓库当成用户行为
        blob = " ".join(str(e.get(k) or "") for k in ("title", "path", "url"))
        if OL_PAT.search(blob):
            hits.append(e)
    if len(hits) < 5:
        return []
    days = {(e.get("ts") or "")[:10] for e in hits if e.get("ts")}
    return [{
        "kind": "openlookout_build",
        "score": 22 + min(15, len(hits) // 10),
        "local": {
            "events": len(hits),
            "days": sorted(days)[-8:],
            "sample_paths": list({(e.get("path") or e.get("title") or "")[:120] for e in hits[:12]})[:6],
        },
        "facts": {
            "ol_events": len(hits),
            "ol_days": len(days),
            "sample_paths": min(6, len(hits)),
        },
    }]


def describe_extra(f):
    k, F = f["kind"], f["facts"]
    if k == "tool_stack_churn":
        return (f"用户在 {F['active_days']} 天里围绕 {F['distinct_agents']} 个 AI 编程代理产生了 {F['tool_events']} 次相关痕迹；"
                f"出现最多的一个占 {F['top_tool_events']} 次、跨 {F['top_tool_days']} 天。")
    if k == "openlookout_build":
        return f"用户本机有 {F['ol_events']} 条与 OpenLookout/瞭望手相关的痕迹，分布在 {F['ol_days']} 天。"
    return str(F)


def evidence_extra(f):
    L, k = f["local"], f["kind"]
    if k == "tool_stack_churn":
        return [f"{t['name']}：{t['events']} 次 / {t['days']} 天" for t in L["tools"]]
    if k == "openlookout_build":
        return [f"相关天数：{'、'.join(L['days'])}"] + [f"样本：{p}" for p in L.get("sample_paths") or [] if p]
    return []


def solve_extra(f, env):
    """为新增 kind 生成基础成品；趋势 kits 在 enhance 里追加。"""
    d = Path(env.run_dir) / "work" / f["id"]
    d.mkdir(parents=True, exist_ok=True)
    k, L, F = f["kind"], f["local"], f["facts"]
    if k == "tool_stack_churn":
        p = d / "ai_tool_stack.csv"
        import csv
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["工具", "事件数", "活跃天数"])
            for t in L["tools"]:
                w.writerow([t["name"], t["events"], t["days"]])
        return {
            "status": "verified",
            "artifacts": [str(p)],
            "slots": {"工具数": str(F["distinct_agents"]), "事件数": str(F["tool_events"]), "天数": str(F["active_days"])},
            "workflow": {"explain": "按痕迹统计你实际碰过的 AI 编程工具栈（只读，不改配置）"},
            "verify_deid": {"tools_listed": len(L["tools"]), "files_touched": 0},
        }
    if k == "openlookout_build":
        p = d / "openlookout_activity.json"
        p.write_text(json.dumps({"events": F["ol_events"], "days": F["ol_days"], "samples": L.get("sample_paths")}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "verified",
            "artifacts": [str(p)],
            "slots": {"事件数": str(F["ol_events"]), "天数": str(F["ol_days"])},
            "workflow": {"explain": "汇总你在本机推进 OpenLookout 的痕迹"},
            "verify_deid": {"events": F["ol_events"], "files_touched": 0},
        }
    return {"status": "omit", "artifacts": [], "slots": {}, "workflow": {"explain": ""}, "verify_deid": {}}


def template_extra(f, r):
    k, F = f["kind"], f["facts"]
    if k == "tool_stack_churn":
        return {
            "title": f"你在 {F['distinct_agents']} 个 AI 编程代理之间来回切换",
            "noticed": "过去 {天数} 天里，和 AI 编程工具相关的痕迹有 {事件数} 次，涉及 {工具数} 个不同代理。",
            "prepared": "工具栈清单；并按外部新能力准备了可直接用的下一步（见趋势引用）。",
            "verified": "统计来自本机历史只读扫描；成品脚本已做过演示模式自检。",
            "question": "要不要用新能力（隔离 worktree）代替再装一个代理？",
            "options": ["要", "不重要", "方向不对"],
        }
    if k == "openlookout_build":
        return {
            "title": "你正在做的 OpenLookout，正好撞上「行为洞察」缺口",
            "noticed": "本机有 {事件数} 条 OpenLookout 相关痕迹（{天数} 天）。",
            "prepared": "活动摘要 + 对照外部已发生的技术变化准备的可运行核对物。",
            "verified": "只读统计；附加成品带自检记录。",
            "question": "下一刀切在「行为×趋势」还是别的？",
            "options": ["就这个", "不重要", "换方向"],
        }
    return {"title": k, "noticed": describe_extra(f), "prepared": "", "verified": "", "question": "", "options": ["知道了"]}


# ---- kits ----
def _kit_pubkey_lab(out_dir: Path, trend: dict) -> list[str]:
    lab = Path(__file__).resolve().parent / "world_kits" / "pubkey_lab"
    arts = []
    # copy module + run a short compare note
    for name in ("pubkey_lab.py", "pqc_compare.py", "test_pubkey_lab.py"):
        src = lab / name
        if src.exists():
            dst = out_dir / name
            shutil.copy2(src, dst)
            arts.append(str(dst))
    note = out_dir / "趋势对照_PQC.md"
    note.write_text(
        f"# 行为卡点 × 趋势\n\n"
        f"- 趋势：{trend.get('id')}（{trend.get('date')}）\n"
        f"- 来源：{trend.get('url')}\n"
        f"- 事实：{trend.get('fact')}\n"
        f"- 新打开的能力：{trend.get('opens')}\n\n"
        f"## 怎么用\n"
        f"```bash\npython3 pubkey_lab.py\npython3 pqc_compare.py\npython3 -m pytest test_pubkey_lab.py -q\n```\n"
        f"把实验里的 RSA/DH/签名结果，对照 OpenSSH/NIST 已落地的后量子原语。\n",
        encoding="utf-8",
    )
    arts.append(str(note))
    # run tests if possible
    try:
        r = subprocess.run([sys.executable, str(out_dir / "test_pubkey_lab.py")],
                           cwd=str(out_dir), capture_output=True, text=True, timeout=60)
        (out_dir / "pubkey_lab_test_log.txt").write_text(
            f"exit={r.returncode}\n{r.stdout}\n{r.stderr}", encoding="utf-8")
        arts.append(str(out_dir / "pubkey_lab_test_log.txt"))
    except Exception as ex:
        (out_dir / "pubkey_lab_test_log.txt").write_text(repr(ex), encoding="utf-8")
    return arts


def _kit_worktree_starter(out_dir: Path, trend: dict) -> list[str]:
    script = out_dir / "try_in_worktree.py"
    script.write_text(
        '''#!/usr/bin/env python3
"""在隔离 git worktree 里试改，而不是再装一个 AI 代理。
用法：python3 try_in_worktree.py [--do] [branch-suffix]
默认只演示；加 --do 才创建 worktree（要求当前目录是 git 仓库）。
"""
import argparse, subprocess, sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("suffix", nargs="?", default="agent-try")
    ap.add_argument("--do", action="store_true")
    a = ap.parse_args()
    root = Path.cwd()
    if not (root / ".git").exists() and not (root / ".git").is_file():
        # also allow gitdir
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("这里不是 git 仓库。请先 cd 到项目根。")
    branch = f"try/{a.suffix}"
    dest = root.parent / f"{root.name}-{a.suffix}"
    cmds = [
        ["git", "branch", branch],
        ["git", "worktree", "add", str(dest), branch],
    ]
    print(f"将创建分支 {branch}")
    print(f"将添加 worktree → {dest}")
    print("然后在新目录里开你常用的代理即可；主目录保持不动。")
    if not a.do:
        print("演示模式：未执行。确认后加 --do。")
        return
    # create branch if missing
    subprocess.run(["git", "branch", branch], check=False)
    r = subprocess.run(["git", "worktree", "add", str(dest), branch], capture_output=True, text=True)
    print(r.stdout or r.stderr)
    if r.returncode != 0:
        sys.exit(r.returncode)
    print("完成。")

if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )
    note = out_dir / "趋势对照_Worktree.md"
    note.write_text(
        f"# 行为卡点 × 趋势\n\n"
        f"- 趋势：{trend.get('id')}（{trend.get('date')}）\n"
        f"- 来源：{trend.get('url')}\n"
        f"- 事实：{trend.get('fact')}\n"
        f"- 新打开的能力：{trend.get('opens')}\n\n"
        f"## 怎么用\n```bash\npython3 try_in_worktree.py          # 演示\npython3 try_in_worktree.py --do lab7\n```\n",
        encoding="utf-8",
    )
    # dry-run self check
    repo_root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(script)], cwd=str(repo_root),
                       capture_output=True, text=True, timeout=30)
    log = out_dir / "worktree_starter_dryrun.txt"
    log.write_text(f"exit={r.returncode}\n{r.stdout}\n{r.stderr}", encoding="utf-8")
    return [str(script), str(note), str(log)]


def _kit_dmcbom_self(out_dir: Path, trend: dict) -> list[str]:
    dmc = Path(__file__).resolve().parent.parent / "opportunities" / "dual-migration-cbom" / "dmcbom.py"
    if not dmc.exists():
        return []
    target = Path(__file__).resolve().parent.parent  # openlookout repo
    out_json = out_dir / "openlookout.cbom.json"
    out_md = out_dir / "openlookout_迁移清单.md"
    try:
        r = subprocess.run(
            [sys.executable, str(dmc), str(target), "--cbom", str(out_json), "--md", str(out_md)],
            capture_output=True, text=True, timeout=120,
        )
        (out_dir / "dmcbom_log.txt").write_text(f"exit={r.returncode}\n{r.stdout}\n{r.stderr}", encoding="utf-8")
    except Exception as ex:
        (out_dir / "dmcbom_log.txt").write_text(repr(ex), encoding="utf-8")
        return [str(out_dir / "dmcbom_log.txt")]
    arts = [str(out_dir / "dmcbom_log.txt")]
    note = out_dir / "趋势对照_OpenLookout.md"
    note.write_text(
        f"# 行为卡点 × 趋势\n\n"
        f"- 趋势：{trend.get('id')}（{trend.get('date')}）\n"
        f"- 来源：{trend.get('url')}\n"
        f"- 事实：{trend.get('fact')}\n"
        f"- 新打开的能力：{trend.get('opens')}\n\n"
        f"对 OpenLookout 本仓库跑了国密×PQC 双迁移扫描（若生成了 CBOM/清单见同目录）。\n",
        encoding="utf-8",
    )
    arts.append(str(note))
    for p in (out_json, out_md):
        if p.exists():
            arts.append(str(p))
    return arts


KIT_BUILDERS = {
    "pubkey_lab": _kit_pubkey_lab,
    "worktree_starter": _kit_worktree_starter,
    "dmcbom": _kit_dmcbom_self,
}


def enhance(f: dict, result: dict, env, catalog: dict | None = None) -> dict:
    """给已求解结果挂趋势引用，并按 kits 追加成品。"""
    if result.get("status") in ("omit", "failed", "reminder_only", "skipped"):
        return result
    matched = T.match_trends(f, catalog)
    if not matched:
        result["trends"] = []
        return result
    cites = [T.cite(t) for t in matched]
    result["trends"] = cites
    # build kits from top trend first
    kit_dir = Path(env.run_dir) / "work" / f["id"] / "trend_kits"
    kit_dir.mkdir(parents=True, exist_ok=True)
    extra_arts = []
    kit_errors = []
    used = set()
    for t in matched:
        for kit in t.get("kits") or []:
            if kit in used:
                continue
            builder = KIT_BUILDERS.get(kit)
            if not builder:
                continue
            used.add(kit)
            try:
                kit_out = kit_dir / kit
                kit_out.mkdir(parents=True, exist_ok=True)
                arts = builder(kit_out, t)
                extra_arts.extend(arts)
            except Exception as ex:
                err = kit_dir / f"{kit}_error.txt"
                err.write_text(repr(ex), encoding="utf-8")
                kit_errors.append({"kit": kit, "error": repr(ex)[:300], "log": str(err)})
    if extra_arts:
        result.setdefault("artifacts", []).extend(extra_arts)
        vd = result.setdefault("verify_deid", {})
        vd["trend_kits"] = sorted(used)
        vd["trend_ids"] = [c["id"] for c in cites]
        if kit_errors:
            vd["trend_kit_errors"] = kit_errors
        wf = result.setdefault("workflow", {})
        wf["explain"] = (wf.get("explain") or "") + f"；已按趋势 {', '.join(c['id'] for c in cites)} 追加可运行成品"
    if kit_errors:
        result["status"] = "failed"
        result["error"] = "趋势成品构建失败：" + ", ".join(item["kit"] for item in kit_errors)
    # latent boost marker for surprise
    result["trend_opens"] = [c.get("opens") for c in cites if c.get("opens")]
    return result


EXTRA_KINDS = {"tool_stack_churn", "openlookout_build"}
