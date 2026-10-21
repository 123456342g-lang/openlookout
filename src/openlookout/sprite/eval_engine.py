"""变异检查（引擎/风险层，T8）：故意改坏风险模型或引擎闸门，确认 eval_all 会抓红。

eval_mutate.py 只覆盖核心 watch 管线的 8 个变异体；本文件补上「场景层」的缺口：
风险模型（classify_file/classify_proc）与引擎闸门（high 不做 / medium 不自信不做）。
做法与 eval_mutate 一致：monkeypatch 改坏机制 -> 重跑 eval_all -> 误操作必须 > 0，否则该变异体 SURVIVED（用例有缺口）。

用法：python -m sprite.eval_engine
"""
from __future__ import annotations
import json, sys
from contextlib import contextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sprite import risk as R            # noqa: E402
from sprite import eval_all             # noqa: E402
from sprite.framework import Engine     # noqa: E402
from sprite.framework import Outcome    # noqa: E402


def _patch(mod, attr, new):
    old = getattr(mod, attr)
    setattr(mod, attr, new)
    try:
        yield
    finally:
        setattr(mod, attr, old)


@contextmanager
def _classify_file_all_safe():
    """风险模型变异：文件一律当成可再生缓存（等价于有人把 temp/cache 判定改宽）。"""
    from sprite.risk import Risk
    return _patch(R, "classify_file", lambda p, env: Risk("safe", "变异：文件一律当可再生缓存", True, "quarantine"))


@contextmanager
def _classify_proc_all_safe():
    """风险模型变异：进程一律可挂起（等价于有人删掉受保护/编辑器/前台判定）。"""
    from sprite.risk import Risk
    return _patch(R, "classify_proc", lambda pr, our_pid=None: Risk("safe", "变异：进程一律可挂起", True, "suspend"))


@contextmanager
def _engine_gates_off():
    """引擎闸门变异：去掉「high 不做 / 不可还原不做 / medium 不自信不做」三道门（其余逻辑原样）。"""
    def loose_handle(self, sc, pb, world):
        out = Outcome(pb, sc.name)
        cands = sc.propose(pb, world)
        cands.sort(key=lambda a: (a.risk == "high", -a.relief, a.blast_bytes))
        remaining = pb.need
        floor = pb.need * self.gate.get("min_gain_frac", 0.05) if pb.need else 0
        if pb.kind == "mem":
            floor = min(floor, 100.0)
        for a in cands:
            tr = self.ledger.trust(a.kind)
            # 变异点：不再跳过 high / 不可还原 / medium 不自信
            if pb.need > 0:
                if pb.recheck:
                    remaining = min(remaining, pb.recheck())
                if remaining <= 0:
                    out.skipped.append((a, "问题已缓解，不多做")); continue
            est = self.estimate(a, pb)
            if not est["ok"]:
                out.skipped.append((a, f"价值不够（{est['value_s']}s vs {est['cost_s']}s）")); continue
            if pb.need > 0 and a.relief and a.value_s is None and a.relief < floor:
                out.skipped.append((a, "边际收益太小：不做")); continue
            if a.blast_items > sc.auto_caps["items"] or a.blast_bytes > sc.auto_caps["bytes"]:
                out.skipped.append((a, "影响范围超过上限：不做")); continue
            if not a.dry_run():
                out.skipped.append((a, "dry-run 没通过")); continue
            try:
                a.result = a.run()
                if not a.verify(a.result):
                    a.undo(a.result); self.ledger.rec(a.kind, "failed"); out.skipped.append((a, "事后校验失败，已还原")); continue
            except Exception as e:
                try:
                    a.undo(a.result or {})
                except Exception:
                    pass
                self.ledger.rec(a.kind, "failed"); out.skipped.append((a, f"执行出错已回滚：{type(e).__name__}")); continue
            self.ledger.rec(a.kind, "ok"); self.live[a.id] = a
            out.acted.append(a); remaining -= a.relief
        if pb.need and pb.recheck:
            remaining = min(remaining, pb.recheck())
        out.relieved = pb.need - max(remaining, 0) if pb.need else 0
        if out.acted:
            out.text_done = (sc.group_text(out.acted, pb) if sc.group_text else "；".join(a.done_text([a]) for a in out.acted))
            out.text_short = (sc.group_short(out.acted, pb) if sc.group_short else
                              ("、".join((a.done_short or a.done_text)([a]) for a in out.acted[:2]) + ("等" if len(out.acted) > 2 else "")))
        return out
    return _patch(Engine, "handle", loose_handle)


MUTANTS = [
    ("classify-file-always-safe", "风险模型：文件一律当可再生缓存", _classify_file_all_safe),
    ("classify-proc-always-safe", "风险模型：进程一律可挂起", _classify_proc_all_safe),
    ("engine-gates-off", "引擎：去掉 high/不可还原/medium 不自信三道闸门", _engine_gates_off),
]
_BY_ID = {m[0]: m for m in MUTANTS}


def _evaluate_under(ctx):
    """在变异体生效时跑一次 eval_all；每个变异体独立子进程，峰值磁盘=单次 evaluate。"""
    with ctx():
        return eval_all.evaluate()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "--run":            # 子进程模式：单变异体
        mid = argv[1]; _, _, ctx = _BY_ID[mid]
        print(json.dumps(_evaluate_under(ctx), ensure_ascii=False))
        return 0
    import subprocess
    base = eval_all.evaluate()
    if base["wrongful"] != 0:
        print(f"基线就不干净：{base['traps']} 陷阱 / {base['wrongful']} 误操作 —— 先修基线再谈变异")
        return 2
    print(f"基线：{base['traps']} 陷阱 / 0 误操作 / {base['positives']} 正例 / {base['missed']} 漏做\n")
    survived = []
    for mid, desc, _ctx in MUTANTS:
        r = json.loads(subprocess.check_output([sys.executable, "-m", "sprite.eval_engine", "--run", mid],
                                               cwd=str(_ROOT), env={**__import__("os").environ, "TEMP": __import__("tempfile").gettempdir()}))
        caught = r["wrongful"] > 0
        tag = "CAUGHT" if caught else "SURVIVED"
        print(f"{tag:9} {mid:28} {desc}")
        print(f"          变异后误操作 = {r['wrongful']}（陷阱 {r['traps']} / 正例 {r['positives']} / 漏做 {r['missed']}）")
        if not caught:
            survived.append(mid)
    print()
    if survived:
        print("漏网变异体（用例有缺口，需补用例）：", ", ".join(survived))
        return 1
    print("全部引擎/风险层变异体都被抓到：用例集对这些机制有约束力。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
