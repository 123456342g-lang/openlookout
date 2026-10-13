import os, time, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sprite.framework import Engine, Registry
from sprite.conventions import ConventionLearner, is_instruction, rule_lines
from sprite.capability import FixtureIndex, Candidate, VerifierPolicy
from sprite.reinvention import ReinventionProvider
from sprite.scenarios import conventions as scv, resource
from sprite.risk import Env

NOW = datetime.now(timezone.utc)
iso = lambda d: (NOW - timedelta(days=d)).isoformat().replace("+00:00", "Z")


def cand(name, desc, lic="MIT", stars=5000, idle=10, **kw):
    return Candidate(name, "", dict(license=lic, archived=False, pushed_at=iso(idle), adoption=stars, description=desc, topics=[], fork=False, **kw))


def ev(days_ago, text, proj, kind="instruction", session=None):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return dict(ts=ts, kind=kind, text=text, project=str(proj), session=session or f"s{days_ago}")


def world(tmp, instr=()):
    w = resource.World(env=Env(now=time.time()), home=tmp); w.instructions = list(instr); return w


def run(tmp, proj_list, w, providers=(), learner=None):
    sc = scv.make(learner or ConventionLearner(), lambda w: proj_list, providers=providers)
    reg = Registry(); reg.register(sc); e = Engine(reg, tmp)
    return e, sc, e.step(w)


def mkproj(tmp, name, rules=None):
    p = tmp / name; p.mkdir(); (p / ".git").mkdir()
    for f, t in (rules or {}).items(): (p / f).write_text(t, "utf-8")
    return p


def test_instruction_detector_and_traps():
    assert is_instruction("改完代码一定要先跑测试再说完成") and is_instruction("Always run the tests before you say it's done")
    assert not is_instruction("今天天气不错") and not is_instruction("要不要别用tab？") and not is_instruction("好的")


def test_several_different_conventions_learned_and_persisted(tmp_path):
    p = mkproj(tmp_path, "app", {"AGENTS.md": "# 规则\n- 用中文回答\n", "CLAUDE.md": "# claude\n"})
    q = mkproj(tmp_path, "other")
    I = []
    for d, t in ((9, "不要把 .env 和密钥提交到仓库"), (5, "别把密钥和 .env 文件提交到仓库里"), (1, "不要把 .env、密钥提交到仓库")): I.append(ev(d, t, p))
    for d, t in ((8, "改完代码一定要先跑测试再说完成"), (4, "写完代码记得先跑测试再说完成"), (2, "改完一定要先跑测试，再说完成")): I.append(ev(d, t, p))
    for d, t in ((7, "提交信息请用中文，别用英文"), (3, "提交信息要用中文，不要用英文"), (1, "提交信息也要用中文，别用英文")): I.append(ev(d, t, p))
    for d, t in ((6, "先看看有没有现成的开源库，别自己从零写"), (3, "别自己从零写，先找现成的开源库"), (1, "先找找有没有现成的开源库，不要自己从零写")): I.append(ev(d, t, p))
    for d, t in ((8, "接口返回必须带 request_id"), (2, "接口返回一定要带 request_id")): I.append(ev(d, t, q))          # 只有两次：不够
    e, sc, outs = run(tmp_path, [str(p), str(q)], world(tmp_path, I))
    acted = [a for o in outs for a in o.acted]
    assert len(acted) == 4, [o.problem.evidence for o in outs]
    agents = (p / "AGENTS.md").read_text(); claude = (p / "CLAUDE.md").read_text()
    for kw in ("密钥", "跑测试", "中文", "开源库"): assert kw in agents and kw in claude              # 每个工具会读的规则文件都写了
    assert "# 规则\n- 用中文回答\n" in agents                                                              # 原有内容保留
    assert not (q / "AGENTS.md").exists()                                                              # 证据不足的项目不动
    assert all(len(o.text_short) <= 40 for o in outs if o.acted)
    # 全部可撤销，字节还原
    for a in reversed(acted): a.undo(a.result)                                                          # 后做的先撤
    assert (p / "AGENTS.md").read_text() == "# 规则\n- 用中文回答\n" and (p / "CLAUDE.md").read_text() == "# claude\n"


def test_false_positive_traps_learn_nothing(tmp_path):
    p = mkproj(tmp_path, "t1", {"AGENTS.md": "# r\n- 改完代码一定要先跑测试再说完成\n"})
    I = []
    for i in range(6): I.append(ev(0, "不要用 var，都用 let/const", p, session="same"))                     # 同一会话里连说 6 遍
    for d in (9, 6, 3, 1): I.append(ev(d, f"不要改 src/main.py 第 {d*10} 行", p))                           # 任务专用
    for d in (9, 5, 1): I.append(ev(d, "缩进必须用tab", p))
    for d in (8, 4, 2): I.append(ev(d, "缩进不要用tab", p))                                                # 自相矛盾
    for d in (9, 5, 1): I.append(ev(d, "改完代码一定要先跑测试再说完成", p))                              # 规则里已有
    for d in (9, 5): I.append(ev(d, "所有日志必须带时间戳", p))                                            # 只有两天
    for d in (9, 5, 1): I.append(ev(d, "要不要别用tab呢？", p)); I.append(ev(d, "好的谢谢", p))             # 不是指令
    e, sc, outs = run(tmp_path, [str(p)], world(tmp_path, I))
    assert outs == [] or not any(o.acted for o in outs), [o.problem.evidence for o in outs]
    assert (p / "AGENTS.md").read_text() == "# r\n- 改完代码一定要先跑测试再说完成\n"
    why = dict((t, r) for t, r in sc.state and [] or [])                                                  # noqa


def test_undo_means_never_propose_again(tmp_path):
    p = mkproj(tmp_path, "u")
    I = [ev(d, t, p) for d, t in ((9, "不要提交 node_modules 到仓库"), (5, "别把 node_modules 提交到仓库"), (1, "不要把 node_modules 提交进仓库"))]
    w = world(tmp_path, I); learner = ConventionLearner(); sc = scv.make(learner, lambda w: [str(p)])
    reg = Registry(); reg.register(sc); e = Engine(reg, tmp_path)
    out = e.step(w)[0]; assert out.acted and "node_modules" in (p / "AGENTS.md").read_text()
    assert e.undo(out.acted[0].id) and not (p / "AGENTS.md").exists()
    sc.state["announced"].clear()                                                                         # 即使重新评估
    assert not any(o.acted for o in e.step(w)) and not (p / "AGENTS.md").exists()


def test_global_convention_across_projects_applies_reversibly(tmp_path):
    ps = [mkproj(tmp_path, f"g{i}", {"AGENTS.md": "# r\n- 所有对外接口必须写文档注释\n"}) for i in range(3)]
    fresh = mkproj(tmp_path, "fresh")
    e, sc, outs = run(tmp_path, [str(x) for x in ps + [fresh]], world(tmp_path))
    acted = [a for o in outs for a in o.acted]
    assert acted and not any(o.asks for o in outs)                                                         # 全局级：也直接做（追加带标记的块，可撤销）
    assert "文档注释" in (fresh / "AGENTS.md").read_text()
    assert all(e.undo(a.id) for a in acted) and not (fresh / "AGENTS.md").exists()


def test_paraphrase_merge_needs_semantic_hook(tmp_path):
    p = mkproj(tmp_path, "sem")
    I = [ev(9, "别自己造轮子，先找现成的库", p), ev(5, "先看看有没有现成的开源项目，不要从零写", p), ev(1, "不要重复造轮子，优先复用成熟库", p)]
    assert not ConventionLearner().infer(I, {})                                                           # 纯本地 n-gram：合并不了释义（诚实的局限）
    merged = ConventionLearner(semantic=lambda a, b: all(k in a + b for k in ()) or ("轮子" in a + b or "现成" in a + b)).infer(I, {})
    assert merged and merged[0].n_events == 3                                                             # 有 tier1/2 语义判断时可合并


# ---------------- 通用“重复造轮子”证据 -> 约定（没有任何类别清单）
def code(n, imports=""): return imports + "\n".join(f"def f{i}(x):\n    return x + {i}" for i in range(n))


def proj_with(tmp, name, files, deps=None, age=3600):
    p = mkproj(tmp, name)
    for rel, text in files.items():
        f = p / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text); os.utime(f, (time.time() - age,) * 2)
    if deps is not None: (p / "requirements.txt").write_text("\n".join(deps))
    return p


TABLE = {"pdf parser": [cand("py-pdf/pypdf", "A pure-python PDF library: parser, text extraction"), cand("x/gpl-pdf", "pdf parser", lic="GPL-3.0"), cand("x/old", "pdf parser", idle=900), cand("x/tiny", "pdf parser", stars=20)],
         "retry": [cand("jd/tenacity", "Retrying library for Python")],
         "image resize": [cand("python-pillow/Pillow", "Python imaging library: image resize, crop, filters", lic="HPND")],           # 许可证不在白名单：不算
         "csv diff": [cand("acme/csvdiff", "Fast csv diff tool", stars=3000)]}


def prov(tmp_projects, table=TABLE, **kw):
    return ReinventionProvider(FixtureIndex(table), VerifierPolicy(), lambda w: tmp_projects, **kw)


def test_reinvention_evidence_becomes_persisted_convention_across_domains(tmp_path):
    a = proj_with(tmp_path, "a", {"src/pdf_parser.py": code(40)}, deps=["flask"])
    b = proj_with(tmp_path, "b", {"lib/csv_diff.py": '"""Compare two csv files."""\n' + code(40)}, deps=[])
    (a / "AGENTS.md").write_text("# 规则\n")
    e, sc, outs = run(tmp_path, [str(a), str(b)], world(tmp_path), providers=[prov([a, b])])
    acted = [x for o in outs for x in o.acted]
    assert len(acted) == 2
    for p, kw in ((a, "pypdf"), (b, "csvdiff")):
        txt = (p / "AGENTS.md").read_text(); assert "新建通用模块前" in txt and kw in txt and (p / "scripts/lookup_existing.py").exists()
    assert "# 规则" in (a / "AGENTS.md").read_text()
    for x in acted: x.undo(x.result)
    assert (a / "AGENTS.md").read_text() == "# 规则\n" and not (b / "AGENTS.md").exists() and not (a / "scripts").exists()


def test_reinvention_false_positive_traps(tmp_path):
    cases = {
        "tiny": proj_with(tmp_path, "c1", {"retry_utils.py": code(5)}, deps=[]),
        "already_depends": proj_with(tmp_path, "c2", {"retry_utils.py": code(40)}, deps=["tenacity"]),
        "thin_wrapper": proj_with(tmp_path, "c3", {"retry_utils.py": "# thin wrapper around tenacity\n" + code(40)}, deps=[]),
        "project_is_the_thing": proj_with(tmp_path, "pdf-parser-lib", {"pdf_parser.py": code(50)}, deps=[]),
        "domain_coupled": proj_with(tmp_path, "c5", {"retry_utils.py": "from billing import ledger\nfrom billing.models import Invoice\nimport accounts\n" + code(40), "billing/__init__.py": "", "accounts.py": ""}, deps=[]),
        "in_tests": proj_with(tmp_path, "c6", {"tests/retry_utils.py": code(50)}, deps=[]),
        "vendored": proj_with(tmp_path, "c7", {"vendor/retry_utils.py": code(50)}, deps=[]),
        "still_writing": proj_with(tmp_path, "c8", {"retry_utils.py": code(50)}, deps=[], age=5),
        "unmatched_name": proj_with(tmp_path, "c9", {"quantum_scheduler_zeta.py": code(80)}, deps=[]),
        "bad_license_only": proj_with(tmp_path, "c10", {"image_resize.py": code(50)}, deps=[]),
    }
    e, sc, outs = run(tmp_path, [str(p) for p in cases.values()], world(tmp_path), providers=[prov(list(cases.values()))])
    assert not any(o.acted for o in outs), [o.problem.evidence for o in outs]
    for n, p in cases.items(): assert not (p / "AGENTS.md").exists() and not (p / "scripts").exists(), n
    # 索引离线/查不到
    p = proj_with(tmp_path, "c11", {"retry_utils.py": code(50)}, deps=[])
    e, sc, outs = run(tmp_path, [str(p)], world(tmp_path), providers=[prov([p], table={})]); assert not any(o.acted for o in outs)
    # 候选只剩没通过核实的
    e, sc, outs = run(tmp_path, [str(p)], world(tmp_path), providers=[prov([p], table={"retry": [cand("x/r", "retry lib", lic="GPL-3.0"), cand("x/old", "retry lib", idle=900)]})]); assert not any(o.acted for o in outs)


def test_user_reminders_and_detector_evidence_both_feed_the_same_learner(tmp_path):
    p = proj_with(tmp_path, "m", {"src/retry_utils.py": code(40)}, deps=[])
    I = [ev(5, "写新模块之前一定要先查一下有没有现成的方案", p), ev(1, "别自己写了，先查现成的方案", p)]                       # 两条提醒单独不够（0.59）
    sc = scv.make(ConventionLearner(), lambda w: [str(p)], providers=[prov([p])])
    reg = Registry(); reg.register(sc); e = Engine(reg, tmp_path)
    outs = e.step(world(tmp_path, I)); assert any(o.acted for o in outs)                                  # 加上一次核实过的重复造轮子证据，就够了
