"""终态词表回归（T5）。

背景（见 docs/AUTO_ACTION_OUTCOME_AUDIT.md）：offers.jsonl 里 36 条 auto_failed 的 error
字面全是 ``returncode:0``，对应的运行归档全是 ``closed status=stopped``、0 个 final_response。
也就是说旧词 auto_failed 记的是「这一段运行没有提交最终结论」，不是「操作失败」——名字与语义相反。

这里钉住修好之后的契约：
  1. answered=True                -> auto_completed
  2. 未提交结论、退出码 0          -> auto_no_answer（不得再落成 auto_failed）
  3. 退出码非 0                   -> auto_errored
  4. 回归断言：returncode:0 的未提交结论运行，永远不能再被记成 auto_failed
  5. 记录运行目录与「成功的机器改动数」，读账本的人据此说真话
  6. conversation.history 同时容得下历史 auto_failed 行与新词（历史行不能被重新解释，也不能被丢掉）
"""
from __future__ import annotations

import json
import subprocess

from sprite.i18n import t

import sprite.proactive.conversation as conv
import sprite.proactive.live as livemod


def _run(tmp_path, monkeypatch, stdout, code=0):
    """跑一次 run_offer，返回 (fake_run, 气泡消息列表, 最后一行账本)。"""
    monkeypatch.setattr(livemod, "DIR", tmp_path)
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, code, stdout, "")

    monkeypatch.setattr(livemod.subprocess, "run", fake_run)
    messages = []
    livemod.run_offer({"id": "offer-1", "text": "整理桌面", "kind": "offer"}, messages.append)
    rows = [json.loads(line) for line in (tmp_path / "offers.jsonl").read_text("utf-8").splitlines()]
    return seen, messages, rows[-1]


def test_answered_run_is_auto_completed(tmp_path, monkeypatch):
    stdout = json.dumps({"answered": True, "final": "已整理，随时可以撤回。", "action_results": []})
    _, messages, row = _run(tmp_path, monkeypatch, stdout)
    assert row["result"] == "auto_completed"
    assert messages == [{"kind": "action", "text": "已整理，随时可以撤回。", "action_id": "offer-1"}]


def test_unanswered_run_is_no_answer_not_failed(tmp_path, monkeypatch):
    stdout = json.dumps({"answered": False, "final": None, "report": None, "action_results": []})
    _, messages, row = _run(tmp_path, monkeypatch, stdout)
    assert row["result"] == "auto_no_answer"
    assert row["result"] != "auto_failed"
    assert row["error"] == "no_final_answer"
    assert "returncode:0" not in json.dumps(row, ensure_ascii=False)
    assert messages[-1]["kind"] == "say"
    assert messages[-1]["text"] == t("no_answer_clean")


def test_nonzero_returncode_is_auto_errored(tmp_path, monkeypatch):
    stdout = json.dumps({"answered": False, "action_results": []})
    _, _, row = _run(tmp_path, monkeypatch, stdout, code=1)
    assert row["result"] == "auto_errored"
    assert row["error"] == "returncode:1"


def test_regression_zero_returncode_unanswered_never_auto_failed(tmp_path, monkeypatch):
    """旧行为：final 文本为空就写 auto_failed，error 里还带着 returncode:0。钉死它。"""
    stdout = json.dumps({"answered": False, "final": "", "action_results": []})
    _, _, row = _run(tmp_path, monkeypatch, stdout)
    assert not (row["result"] == "auto_failed" and row.get("error") == "returncode:0")
    assert row["error"] == "no_final_answer"


def test_companion_say_survives_as_the_no_answer_report(tmp_path, monkeypatch):
    """真实情形（10-11 那 18 条）：运行以 companion 留言结束。留言必须留在账本与气泡里。"""
    say = "我把后台闲置的 ChatGPT 内存还给了系统，可用内存回到 1.2GB，没有结束任何程序。"
    stdout = json.dumps({"answered": False, "report": say, "action_results": []})
    _, messages, row = _run(tmp_path, monkeypatch, stdout)
    assert row["result"] == "auto_no_answer"
    assert row["report"] == say
    assert messages[-1]["text"] == say


def test_run_dir_and_mutation_count_are_recorded(tmp_path, monkeypatch):
    stdout = json.dumps({
        "answered": False,
        "action_results": [
            {"tool": "desktop_inventory", "success": True, "text": "看了"},
            {"tool": "desktop_trim", "success": True, "text": "剪了"},
            {"tool": "desktop_trim", "success": False, "text": "被拒"},
        ],
    })
    seen, messages, row = _run(tmp_path, monkeypatch, stdout)
    assert row["mutations"] == 1
    assert "desktop_runs" in row["run_dir"]
    argv = seen["argv"]
    assert argv[argv.index("--directory") + 1] == row["run_dir"]
    assert messages[-1]["text"] == t("no_answer_mutations", n=1)


def test_successful_mutation_count_ignores_read_only_tools():
    result = {"action_results": [
        {"tool": "basic_search", "success": True},
        {"tool": "desktop_processes", "success": True},
        {"tool": "desktop_trim", "success": True},
        {"tool": "desktop_trim", "success": False},
    ]}
    assert livemod._successful_mutation_count(result) == 1
    assert livemod._successful_mutation_count({}) == 0
    assert livemod._successful_mutation_count({"action_results": "nonsense"}) == 0


def test_history_renders_legacy_and_new_terminal_words(tmp_path, monkeypatch):
    monkeypatch.setattr(conv, "DIR", tmp_path)
    # LOG 是模块级常量（conversation.py:16），只补 DIR 还会去读真实 conversation.jsonl。
    monkeypatch.setattr(conv, "LOG", tmp_path / "conversation.jsonl")
    rows = [
        {"id": "a", "t": 1, "text": "清理 C 盘", "kind": "offer", "result": "auto_failed", "t_answer": 2},
        {"id": "b", "t": 3, "text": "把闲置内存还回去", "kind": "offer", "result": "auto_no_answer",
         "t_answer": 4, "mutations": 3},
        {"id": "c", "t": 5, "text": "换供应商", "kind": "offer", "result": "auto_no_answer",
         "t_answer": 6, "mutations": 0},
        {"id": "d", "t": 7, "text": "整理桌面", "kind": "offer", "result": "auto_errored",
         "t_answer": 8, "error": "returncode:1"},
    ]
    (tmp_path / "offers.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    labels = [r["text"] for r in conv.history()]
    assert len(labels) == 4, labels
    assert labels[1] == t("no_answer_mutations", n=3)
    assert labels[2] == t("no_answer_clean")
    assert labels[3] == t("errored_hist")
    assert "没有改动" not in labels[0]  # 历史行的文案不再声称机器没被动过
