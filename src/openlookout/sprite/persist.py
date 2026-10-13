"""通用的“把约定落在工具会读的地方”：规则文件/配置片段/预检脚本，作为带类型的动作（风险、可逆性）接入框架。
目标=项目里已存在的各类代理/工具规则文件（用到哪个就写哪个），一个都没有才新建 AGENTS.md；以追加一段带标记的块的方式，可完整撤销（原字节还原）。"""
from __future__ import annotations
from pathlib import Path
from . import fsexec
from .framework import Action

TARGETS = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", ".windsurfrules", ".github/copilot-instructions.md"]


def targets(proj: Path) -> list:
    t = [f for f in TARGETS if (proj / f).is_file()]
    return t or ["AGENTS.md"]


def block(conv) -> str:
    ev = "\n".join(f"  - 依据：{e[:90]}" for e in conv.evidence[-3:])
    return (f"\n<!-- openlookout:conv:{conv.id} -->\n- {conv.text}\n{ev}\n  - （OpenLookout 小精灵根据 {conv.n_events} 条证据、置信度 {conv.confidence:.0%} 自动加入，可删）\n<!-- /openlookout:conv:{conv.id} -->\n")


def plan(proj: Path, conv) -> list:
    ops = [dict(op="append", dst=f, content=block(conv)) for f in targets(proj)]
    if conv.helper and not (proj / conv.helper["path"]).exists(): ops.append(dict(op="write", dst=conv.helper["path"], content=conv.helper["content"]))
    return ops


def persist_action(world, proj: Path, conv, rejected_cb=None) -> Action:
    proj = Path(proj); ops = plan(proj, conv); jp = Path(world.home) / f"conv_{conv.id}_{abs(hash(str(proj))) % 10**6}.json"
    scope_global = conv.scope == "global"
    n = conv.n_events
    return Action("persist_convention", f"把约定写进 {proj.name} 的规则文件", "medium" if scope_global else "safe", "full", blast_items=len(ops), confident=True,
                  value_s=max(60.0, 40.0 * n * 6), later=f"{n} 条证据显示你会反复提醒/纠正这件事", reason=f"置信度 {conv.confidence:.0%}，{conv.days} 天，{n} 条证据",
                  dry_run=lambda: bool(ops), run=lambda: dict(journal=str(jp), ops=fsexec.execute(proj, ops, jp)),
                  verify=lambda r: all(f"openlookout:conv:{conv.id}" in (proj / o["dst"]).read_text("utf-8") for o in ops if o["op"] == "append"),
                  undo=lambda r: (fsexec.undo(r["journal"]), rejected_cb and rejected_cb(conv)),
                  done_text=lambda xs: f"在 {proj.name} 的 {'、'.join(o['dst'] for o in ops if o['op']=='append')} 里记下约定：{conv.text}",
                  done_short=lambda xs: f"{proj.name} 规则里记下了：{conv.text[:16]}", ask_text=f"把“{conv.text[:24]}”写进 {proj.name} 的规则")
