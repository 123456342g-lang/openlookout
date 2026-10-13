"""小精灵安全评测闸（T8 的对抗用例侧）。

⚠️ 命名说明：`eval_all.py` 与 `eval_risk.py` 已被并行任务的 agent 占用
（前者是全场景对抗评测，后者是风险判定的基础评测）。本模块只用
`eval_cases.py` / `eval_mutate.py`，避免互相覆盖。

跑法（在 src/openlookout 下）：
    python -m sprite.eval_gate# 全部用例 + 引擎守卫 + 变异检查
    python -m sprite.eval_gate --list          # 只列用例
    python -m sprite.eval_gate --only ID,ID     # 只跑指定用例
    python -m sprite.eval_gate --risk unsaved   # 只跑某类风险
    python -m sprite.eval_gate --no-mutate      # 跳过变异检查（快）
    python -m sprite.eval_gate -v              # 打印违规细节

退出码：0 = 没有新增误操作；1 = 有新增误操作或守卫失败；2 = 有变异体漏网。

**当前状态：有 4 条用例是红的，它们是真 bug，不是用例写错。**
每条都在 KNOWN_FAILURES 里带file:line 证据；修好后从该表移除即可。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sprite import eval_cases as EC  # noqa: E402

# ------------------------------------------------------------------ 已知真 bug
# T8 评测发现的**真实缺陷**。修好之后从这里移除，闸门会重新要求该用例通过。
KNOWN_FAILURES = {
    "unsaved-open-doc": dict(
        where="sprite/core.py:92（分组时只跳过 ~$ 文件本身，没跳过被它锁住的那个）",
        what="Word/WPS 打开文档时会生成 ~$xxxx 锁文件。版本化只按 base_stem 分组，"
             "~$报告.docx 的 stem 是「~$报告」，与「报告」不同组——所以被排除的只是锁文件，"
             "**打开着的文档本身**仍然被改名成 报告_v01.docx。",
        why="用户正在编辑的文档被改名：编辑器里的保存目标消失，可能丢改动。",
        fix="检测到同目录存在 ~$xxx 时，连 xxx 本身一起跳过（而不只是跳过 ~$xxx）。",
    ),
    "unsaved-inprogress-download": dict(
        where="lookout/insight/closed_loop/catalog.py:115(_files) vs sprite/core.py:25 (snapshot)",
        what="snapshot() 跳过了 .part/.crdownload/.tmp，但去重用的 _files() 只过滤 . 前缀，"
             "不看后缀，于是未完成的下载分片被纳入去重计划。",
        why="浏览器还在往 big.zip.part 写，精灵把它move 走；用户的下载会中断或失败。",
        fix="让 _files 与 snapshot 共用同一个跳过谓词（抽成 SKIP 常量）。",
    ),
    "lookalike-zero-byte": dict(
        where="lookout/insight/closed_loop/catalog.py:207-219(DownloadDedupe.plan)",
        what="去重只按 sha256 分组。0 字节文件的哈希恒等，所以任意多个空文件都被判为「彼此重复」。",
        why="空文件常是占位符或被占用中的目标文件，被搬走会让用户的应用报错。",
        fix="分组前跳过 size==0 的文件（哈希分组对空文件没有意义）。",
    ),
    "lookalike-cross-type": dict(
        where="lookout/insight/closed_loop/catalog.py:207-219 (DownloadDedupe.plan)",
        what="去重只按 sha256 分组，扩展名与文件名完全不参与判断，"
             "所以 合同.pdf 与 备份说明.txt 只要字节相同就会被当成重复。",
        why="同内容但语义完全不同的文件被隔离到 _dupes，用户在原目录找不到它。",
        fix="至少要求扩展名一致；更稳妥是要求 stem 也一致，或只处理名字带 (1)/(2) 副本标记的文件。",
    ),
}

RISK_LABEL = {
    "unsaved": "没保存的文档",
    "lookalike": "看起来像缓存的用户数据",
    "inuse": "正在被使用的目录",
    "escape": "越界与路径安全",
    "limits": "开关与上限",
    "undo": "撤销与可还原",
    "positive": "该做就要做",
}


def _main(argv=None):
    ap = argparse.ArgumentParser(prog="sprite.eval_gate",
                                 description="小精灵安全评测闸：误操作必须为 0")
    ap.add_argument("--list", action="store_true", help="只列出用例")
    ap.add_argument("--only", help="逗号分隔的用例 id")
    ap.add_argument("--risk", choices=EC.RISKS, help="只跑某一类风险")
    ap.add_argument("--no-mutate", action="store_true", help="跳过变异检查")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    if a.list:
        print(f"用例 {len(EC.CASES)} 条，引擎守卫 {len(EC.GUARDS)} 条\n")
        for c in EC.CASES:
            known = "  [已知真 bug]" if c.id in KNOWN_FAILURES else ""
            print(f"  {c.id:32} {c.risk}{known}")
            print(f"      {c.title}")
            print(f"      来源: {c.provenance}")
        return 0

    cases = EC.select(ids=a.only.split(",") if a.only else None, risk=a.risk)
    if not cases:
        print("没有匹配的用例")
        return 0

    print("=" * 74)
    print("小精灵安全评测闸 —— 全局规则 2：误操作必须为 0")
    print("=" * 74)

    results = [EC.run_case(c) for c in cases]

    print("\n【场景用例】")
    by_risk = {}
    for r in results:
        by_risk.setdefault(r.case.risk, []).append(r)
    for risk in EC.RISKS:
        rs = by_risk.get(risk)
        if not rs:
            continue
        print(f"\n  ── {RISK_LABEL[risk]} ({risk}) ──")
        for r in rs:
            known = r.case.id in KNOWN_FAILURES
            mark = ("FAIL*" if (not r.ok and known) else r.status)
            print(f"  {mark:6} {r.case.id:32} {r.case.title}")
            if r.ok:
                continue
            if a.verbose or known:
                for v in r.violations:
                    print(f"      - {v}")
            else:
                print(f"      - {len(r.violations)} 条违规（-v 看细节）")
            if known and not a.verbose:
                print(f"      已知真 bug: {KNOWN_FAILURES[r.case.id]['where']}")

    print("\n【引擎守卫】")
    guard_fail = 0
    for name, vs in EC.run_guards():
        print(f"  {'PASS' if not vs else 'FAIL':6} {name}")
        for v in vs:
            print(f"      - {v}")
        guard_fail += bool(vs)

    fail = [r for r in results if not r.ok]
    known_fail = [r for r in fail if r.case.id in KNOWN_FAILURES]
    unknown_fail = [r for r in fail if r.case.id not in KNOWN_FAILURES]
    unexpected_pass = [r for r in results if r.ok and r.case.id in KNOWN_FAILURES]

    print("\n" + "=" * 74)
    print(f"用例 {len(results)}  通过 {len(results) - len(fail)}  误操作 {len(fail)}"
          f"（已知真 bug {len(known_fail)}，新增 {len(unknown_fail)}）")
    print(f"引擎守卫 {len(EC.GUARDS)}  失败 {guard_fail}")
    if unexpected_pass:
        print(f"\n注意：{len(unexpected_pass)} 条已知 bug 已不红，请从 KNOWN_FAILURES 移除：")
        for r in unexpected_pass:
            print(f"  - {r.case.id}")

    if known_fail:
        print("\n已知真 bug（不是用例写错，是代码缺陷）：")
        for r in known_fail:
            k = KNOWN_FAILURES[r.case.id]
            print(f"\n  [{r.case.id}]\n    位置: {k['where']}\n"
                  f"    现象: {k['what']}\n    后果: {k['why']}\n    修法: {k['fix']}")

    survived = []
    if not a.no_mutate:
        print("\n" + "=" * 74)
        from sprite import eval_mutate as EM
        rows, survived = EM.run_mutants(verbose=a.verbose)
        print(f"【变异检查】{len(rows)} 个变异体，抓到 "
              f"{sum(1 for r in rows if r['caught'])}，漏网 {len(survived)}")
        if not a.verbose:
            for r in rows:
                print(f"  {'CAUGHT' if r['caught'] else 'SURVIVED':9} {r['mutant'].id}")

    print("\n" + "=" * 74)
    bad = len(unknown_fail) + guard_fail
    if bad:
        print(f"结论：新增误操作 {bad} 处，必须修。")
    elif known_fail:
        print(f"结论：新增误操作 0；另有 {len(known_fail)} 个已知真 bug 待修。")
    else:
        print("结论：误操作 0。")
    if survived:
        print(f"警告：{len(survived)} 个变异体漏网，说明用例集对该机制没有约束力：")
        for s in survived:
            print(f"  - {s}")
    print("=" * 74)

    if bad or survived:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())