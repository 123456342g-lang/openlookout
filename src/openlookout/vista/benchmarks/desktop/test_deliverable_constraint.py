"""`desktop_write_deliverable` 的路径约束到底是真的还是只是描述？

任务简报里问了一个关键问题：工具描述写着「只在 deliverables 目录新建，不覆盖用户
文件」，**核实这个约束在代码里是真的还是只是描述**。

结论（2026-10-13 实测）：**是真的**，而且是三重的 ——
  1. 名字必须是裸文件名（``Path(name).name == name``，且不含 / \\ :）；
  2. 后缀只收 md/txt/csv；
  3. 用 ``open("xb")`` 独占新建，同名文件直接拒绝。

所以精灵**不可能**用它改到 deliverables 之外的任何地方。

那 2026-10-13 它改了 ``E:\\知识产物(必保存)\\...\\v8-audit\\HANDOFF-REMOTE-RCE.md``
是怎么发生的？取证结论记录在 test_bypass_was_not_this_tool.py：那次改动是**宿主
Claude Code 的 Edit 工具**干的（companion 子系统跑的是完整 Claude Code CLI，
带 Read/Edit/Write），不是本项目的工具集干的。本文件把「约束为真」钉死，
免得以后有人误以为描述在骗人而去加没必要的检查。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vista.benchmarks.desktop import permissions
from vista.benchmarks.desktop.actions import DELIVERABLES, desktop_write_deliverable


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """SPRITE_HOME 换成隔离目录，绝不碰真实 sprite_home。"""
    monkeypatch.setattr(permissions, "HOME", tmp_path)
    import vista.benchmarks.desktop.actions as A
    monkeypatch.setattr(A, "HOME", tmp_path)
    monkeypatch.setattr(A, "DELIVERABLES", tmp_path / "deliverables")
    monkeypatch.setattr(A, "JOURNAL", tmp_path / "undo.jsonl")
    return tmp_path


def _args(**over):
    return {"name": "报告.md", "content": "正文", "sources": ["desktop_inventory"], **over}


def test_writes_land_inside_deliverables(isolated):
    reply = desktop_write_deliverable(_args())
    assert reply.success is True
    written = list((isolated / "deliverables").iterdir())
    assert [p.name for p in written] == ["报告.md"]
    payload = json.loads(reply.text)
    assert Path(payload["path"]).parent == isolated / "deliverables"


@pytest.mark.parametrize("name", [
    "../HANDOFF-REMOTE-RCE.md",
    "..\\HANDOFF-REMOTE-RCE.md",
    "sub/dir.md",
    "sub\\dir.md",
    "C:/Windows/x.md",
    "../../../../knowledge/x.md",
    "报告.md.txt/../../escape.md",
])
def test_path_traversal_is_rejected_in_code_not_just_described(isolated, name):
    """穿越尝试必须真的失败，且一个字节都不能落到 deliverables 之外。"""
    reply = desktop_write_deliverable(_args(name=name))
    assert reply.success is False, name
    outside = [p for p in isolated.rglob("*") if "deliverables" not in p.parts]
    assert outside == [], f"{name} 竟然在 deliverables 之外留下了 {outside}"


def test_only_plain_text_suffixes_are_accepted(isolated):
    for name in ("a.exe", "a.ps1", "a.bat", "a.py", "a.sh", "a.dll", "noext"):
        assert desktop_write_deliverable(_args(name=name)).success is False, name
    for name in ("a.md", "a.txt", "a.csv"):
        assert desktop_write_deliverable(_args(name=name)).success is True, name


def test_never_overwrites_an_existing_deliverable(isolated):
    """「不覆盖用户文件」的另一半：同名交付物也不覆盖。"""
    assert desktop_write_deliverable(_args()).success is True
    second = desktop_write_deliverable(_args(content="改了内容"))
    assert second.success is False
    assert (isolated / "deliverables" / "报告.md").read_text("utf-8") == "正文"


def test_underscore_name_cannot_impersonate_a_draft(isolated):
    """``_draft`` 后缀不会让它写到别处 —— 目录仍然被锁死。"""
    assert desktop_write_deliverable(_args(name="../../draft.md")).success is False


def test_journal_records_the_undo_path(isolated):
    desktop_write_deliverable(_args())
    rows = [json.loads(line) for line in (isolated / "undo.jsonl").read_text("utf-8").splitlines()]
    assert rows[-1]["undo_kind"] == "deliverable"
    assert rows[-1]["undo_cmd"] == "desktop_undo"


def test_execution_after_approval_cannot_escape_the_directory(isolated, monkeypatch):
    """批准后重放整条清单，同样锁死在 deliverables 里。

    这是真正要紧的一层：闸门在批准**之后**才执行工具，如果这里有洞，
    那么「一次点头」就会被用来写任意路径。
    """
    original = permissions.HOME
    import vista.benchmarks.desktop.actions as A
    monkeypatch.setattr(A, "HOME", original if False else isolated)
    batch = {"t": __import__("time").time(), "items": [
        {"tool": "desktop_write_deliverable",
         "arguments": _args(name="../../approved-escape.md")},
    ]}
    results = permissions.execute(batch, permissions.Policy())
    assert results[0]["success"] is False
    assert (isolated.parent / "approved-escape.md").exists() is False
