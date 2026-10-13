"""把 T8 对抗用例接进 pytest：`python -m pytest sprite -q` 会一起跑。

已知真 bug（4 条，见 eval_gate.KNOWN_FAILURES）用 xfail 标出来——它们是
代码缺陷而不是用例写错，修好之后 xfail 会变成 XPASS，提醒你把标记删掉。
"""
from __future__ import annotations

import pytest

from sprite import eval_cases as EC
from sprite.eval_gate import KNOWN_FAILURES
from sprite.eval_risk import evaluate as risk_evaluate


def _ids():
    return [c.id for c in EC.CASES]


@pytest.mark.parametrize("cid", _ids())
def test_case(cid):
    c = EC.by_id()[cid]
    r = EC.run_case(c)
    if cid in KNOWN_FAILURES:
        if r.ok:
            pytest.xfail(f"{cid} 已修好——请从 eval_gate.KNOWN_FAILURES 里移除")
        pytest.xfail(f"已知真 bug：{KNOWN_FAILURES[cid]['where']}")
    assert r.violations == [], "\n".join(r.violations)


@pytest.mark.parametrize("name", [n for n, _ in EC.GUARDS])
def test_guard(name):
    fn = dict(EC.GUARDS)[name]
    assert fn() == []


def test_no_wrongful_actions_in_risk_base():
    """风险判定的基础评测：陷阱必须全保住，正例不该漏。"""
    r = risk_evaluate()
    assert r["must_not_touch"] > 0 and r["safe_ok"] > 0
    assert r["wrongful_auto_actions"] == 0, f"误操作 {r['wrongful_auto_actions']} 处"
    assert r["missed_safe"] == 0, f"漏做 {r['missed_safe']} 处"


def test_mutants_all_caught():
    """变异检查：故意改坏安全机制，用例集必须抓得到。"""
    from sprite import eval_mutate as EM
    rows, survived = EM.run_mutants()
    assert not survived, "这些变异体没被抓到，说明用例集有缺口：" + ", ".join(survived)
    assert len(rows) >= 6