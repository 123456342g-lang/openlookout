import os, sys
from pathlib import Path
from sprite.framework import Engine, Registry
from sprite.executors import Task, Backend, CodeExecutor, DesktopExecutor, DocumentExecutor, ExecutorRegistry


def engine(tmp, **kw):
    reg = Registry(); home = tmp / "home"; home.mkdir()
    from sprite.executors import default_registry
    reg.executors = default_registry(home, **kw)
    return Engine(reg, home), reg


def test_code_executor_sandbox_dryrun_backup_undo(tmp_path):
    proj = tmp_path / "proj"; proj.mkdir(); f = proj / "a.py"; f.write_text("x = 1\n")
    e, _ = engine(tmp_path, allowed_code_roots=[proj])
    bad = e.do_task(Task("code", "bad", dict(path=str(f), content="def (:\n")))
    assert not bad.acted and f.read_text() == "x = 1\n"                                 # 语法不通过：沙箱里就拦下，真文件没动
    failing = e.do_task(Task("code", "check fails", dict(path=str(f), content="x = 2\n", root=str(proj), checks=[["{python}", "-c", "import sys; sys.exit(1)"]])))
    assert not failing.acted and f.read_text() == "x = 1\n"
    out = e.do_task(Task("code", "把 x 改成 2", dict(path=str(f), content="x = 2\n", root=str(proj), checks=[["{python}", "-c", "import a; assert a.x == 2"]])))
    assert out.acted and f.read_text() == "x = 2\n" and "撤销" in out.text_short
    assert e.undo(out.acted[0].id) and f.read_text() == "x = 1\n"                        # 撤销=还原备份
    out = e.do_task(Task("code", "again", dict(path=str(f), content="x = 3\n")))
    f.write_text("x = 99  # 你后来自己改的\n")
    e.undo(out.acted[0].id)
    assert "你后来自己改的" in f.read_text() and (proj / "a.py.undo_restored").read_text() == "x = 1\n"      # 不覆盖你之后的改动
    outside = tmp_path / "other.py"; outside.write_text("1\n")
    assert not e.do_task(Task("code", "outside", dict(path=str(outside), content="2\n"))).acted and outside.read_text() == "1\n"   # 不在允许目录


def test_code_executor_new_file_undo_removes_it(tmp_path):
    proj = tmp_path / "p"; proj.mkdir(); e, _ = engine(tmp_path, allowed_code_roots=[proj])
    out = e.do_task(Task("code", "new", dict(path=str(proj / "n.py"), content="y = 1\n")))
    assert (proj / "n.py").exists() and e.undo(out.acted[0].id) and not (proj / "n.py").exists()


def test_document_executor_drafts_only_never_overwrite_never_send(tmp_path):
    dd = tmp_path / "drafts"; e, _ = engine(tmp_path, drafts_dir=dd)
    orig = tmp_path / "report.docx"; orig.write_text("原件")
    o1 = e.do_task(Task("document", "写周报草稿", dict(name="周报.md", content="v1", based_on=str(orig))))
    o2 = e.do_task(Task("document", "再写一份", dict(name="周报.md", content="v2")))
    assert (dd / "周报.md").read_text() == "v1" and (dd / "周报_v2.md").read_text() == "v2" and orig.read_text() == "原件"
    o3 = e.do_task(Task("document", "../../evil", dict(name="../../evil.md", content="z")))
    assert (dd / "evil.md").exists() and not (tmp_path / "evil.md").exists()           # 路径逃逸被压成文件名
    assert e.do_task(Task("document", "发给老板", dict(name="m.md", content="hi", to="boss@x.com"))).acted == []      # 带发送意图：没有执行器接，不做
    assert e.undo(o1.acted[0].id) and not (dd / "周报.md").exists() and list((dd / ".trash").iterdir())            # 撤销=进回收目录


def test_desktop_prefers_api_then_cli_then_file_input_last_resort(tmp_path):
    log = []
    be = {v: Backend(lambda p, v=v: log.append(("do", v)) or v, lambda t, v=v: log.append(("undo", v))) for v in ("api", "cli", "file", "input")}
    ex = DesktopExecutor(be, idle=lambda: 600, cli_allow={"git"})
    step = dict(input=dict(keys="x", undo="ctrl+z"), file=dict(op="mv", undo="mv"), cli=dict(argv=["git", "x"], undo=["git", "y"]), api=dict(call="a", undo="b"))
    a = ex.plan(Task("desktop", "t", dict(steps=[step]))); a.run(); assert log == [("do", "api")]
    step.pop("api"); log.clear(); ex.plan(Task("desktop", "t", dict(steps=[step]))).run(); assert log == [("do", "cli")]
    step["cli"]["argv"] = ["rm", "-rf"]; log.clear(); ex.plan(Task("desktop", "t", dict(steps=[step]))).run(); assert log == [("do", "file")]       # 不在白名单的 CLI 不用
    step.pop("file"); log.clear(); a = ex.plan(Task("desktop", "t", dict(steps=[step]))); assert a.risk == "medium"; a.run(); assert log == [("do", "input")]
    nu = dict(input=dict(keys="x"))                                                                                  # 没有撤销办法：不做
    assert ex.plan(Task("desktop", "t", dict(steps=[nu]))) is None


def test_desktop_input_only_when_idle_and_aborts_on_user_input(tmp_path):
    log = []; idle = [600.0]
    be = {"input": Backend(lambda p: log.append(("do", p["k"])), lambda t: log.append(("undo", t[0]["k"])))}
    ex = DesktopExecutor(be, idle=lambda: idle[0], idle_needed=120)
    steps = [dict(input=dict(k=i, undo="z")) for i in range(3)]
    idle[0] = 5; assert ex.plan(Task("desktop", "t", dict(steps=steps))).dry_run() is False                      # 你在用电脑：不碰
    idle[0] = 600
    seq = iter([600, 700, 800, 0.5]); ex.idle = lambda: next(seq)                                                      # 第 3 步前检测到输入
    a = ex.plan(Task("desktop", "t", dict(steps=steps)))
    try: a.run(); assert False
    except RuntimeError: pass
    assert [x for x in log if x[0] == "undo"] == [("undo", 1), ("undo", 0)]                                       # 已做的步骤被逆序撤销


def test_decision_core_picks_lowest_risk_and_llm_only_for_novel(tmp_path):
    class Cheap(DocumentExecutor): name = "cheap_doc"
    class Pricey(DocumentExecutor):
        name = "pricey_doc"; risk = "medium"
    r = ExecutorRegistry(); r.register(Pricey(tmp_path / "a")); r.register(Cheap(tmp_path / "b"))
    assert r.pick(Task("document", "x", dict(name="n", content="c"))).name == "cheap_doc"
    calls = []
    llm = lambda t: calls.append(1) or dict(kind="document", spec=dict(name="n.md", content="c"))
    assert r.action_for(Task("document", "known", dict(name="n.md", content="c")), llm) is not None and not calls      # 认识的：本地做，不花 token
    assert r.action_for(Task("weird", "novel", {}, novel=True), llm) is not None and len(calls) == 1                    # 新情况：问一次，但仍由本地执行器执行
    assert r.action_for(Task("weird", "novel", {}, novel=False), llm) is None and len(calls) == 1                       # 不是新情况也没人会：不做
