"""变异检查（T8）：故意改坏规则，确认 eval 能抓到。

为什么需要：一份全绿的用例集可能只是**什么都没测**。变异检查反过来验证
「闸门本身有没有牙」——把安全机制改坏，如果 eval 仍然全绿，说明用例没覆盖到那里。

做法：monkeypatch 掉某个安全机制，跑受影响的用例，断言**必须变红**。
若改坏之后仍然全绿，该变异体被标记为 SURVIVED——这是用例集的漏洞，必须补用例。

用法：
  python -m sprite.eval_risk          # 跑全部变异体
  python -m sprite.eval_risk -v       # 打印每条前后对比
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sprite import core as C  # noqa: E402
from sprite import eval_cases as EC  # noqa: E402
from lookout.insight.closed_loop import catalog as K  # noqa: E402
import hashlib as K_hashlib  # noqa: E402

K_BY_ID = K.BY_ID
K_files = K._files
K_base_stem = K.base_stem


@dataclass(frozen=True)
class Mutant:
    id: str
    desc: str                 # 改坏了什么
    cases: tuple              # 受影响的用例
    expect: str               # 期望现象


@contextmanager
def _patched(mod, attr, new):
    old = getattr(mod, attr)
    setattr(mod, attr, new)
    try:
        yield
    finally:
        setattr(mod, attr, old)


# ------------------------------------------------------------------ 变异体
def _m_files_no_filter():
    """_files 不再过滤 ~$ 与 . 前缀（等价于把过滤谓词改窄）。"""
    def fake_files(root, depth=1):
        out = []
        for p in sorted(Path(root).iterdir()):
            if p.is_file():
                out.append(p)
            elif p.is_dir() and depth > 0 and not p.name.startswith(("_", ".")):
                out += fake_files(p, depth - 1)
        return out
    return _patched(importlib.import_module("lookout.insight.closed_loop.catalog"),
                    "_files", fake_files)


def _m_check_no_exists():
    """_check 去掉「目标已存在就拒绝」。"""
    from lookout.insight.closed_loop import catalog as K
    def loose(root, ops):
        seen = set()
        for o in ops:
            for k in ("src", "dst"):
                if o.get(k):
                    K._inside(root, root / o[k])
            if o.get("dst") in seen:
                continue
            seen.add(o.get("dst"))
    return _patched(K, "_check", loose)


def _m_settled_true():
    return _patched(C, "_settled", lambda *a, **k: True)


def _m_cap_off():
    """actions_today 恒为 -1：让 `actions_today() >= daily_cap` 永远为假。"""
    return _patched(C.Sprite, "actions_today", lambda self: -1)


def _m_quiet_off():
    return _patched(C, "in_quiet", lambda *a, **k: False)


def _m_kill_off():
    return _patched(C.Sprite, "killed", lambda self: False)


def _m_no_protected_dir_check():
    """FillNewSeriesDir 不再要求目标目录为空（模拟有人删掉 any(t.iterdir()) 判断）。"""
    return _patched(EC, "_patch_noop", None, optional=True)


def _m_dedupe_group_by_name():
    """让 DownloadDedupe 放弃按内容哈希，改成只认「同 stem 同后缀」。

    这是最贴近真实回归的变异：有人为了「少读几个文件」把哈希分组换成名字分组，
    结果两个不同内容的同名文件被当成重复搬走。

    注意 plan 是在**实例**上打补丁，签名里没有 self。
    """
    def plan(root, **kw):
        ops = []
        groups = {}
        for p in K_files(root, depth=0):
            groups.setdefault((K_base_stem(p.name), p.suffix.lower()), []).append(p)
        for (base, ext), fs in sorted(groups.items()):
            if len(fs) < 2:
                continue
            fs.sort(key=lambda p: (p.stat().st_mtime, p.name))
            for p in fs[1:]:
                ops.append(dict(op="move", src=p.name, dst=f"_dupes/{p.name}"))
        return ops
    return _patched(K_BY_ID["dedupe"], "plan", plan)


def _m_dedupe_ignore_empty():
    """让去重把 0 字节占位文件也纳入搬走范围。"""
    orig = K_BY_ID["dedupe"].plan

    def plan(root, **kw):
        ops = orig(root, **kw)
        extra = [dict(op="move", src=p.name, dst=f"_dupes/{p.name}")
                 for p in K_files(root, depth=0) if p.is_file() and p.stat().st_size == 0]
        return ops + extra
    return _patched(K_BY_ID["dedupe"], "plan", plan)


def _m_dedupe_recurses():
    """让去重递归进子目录（真实回归：有人把 depth=0 改成了 depth=1+）。"""
    def plan(root, **kw):
        ops = []
        by = {}
        for p in K_files(root, depth=5):
            if p.name.startswith("_"):
                continue
            by.setdefault(K_hashlib.sha256(p.read_bytes()).hexdigest(), []).append(p)
        for h, fs in sorted(by.items()):
            if len(fs) < 2:
                continue
            fs.sort(key=lambda p: (p.stat().st_mtime, p.name))
            for p in fs[1:]:
                ops.append(dict(op="move", src=str(p.relative_to(root)),
                                dst="_dupes/" + str(p.relative_to(root)).replace("\\", "/")))
        return ops
    return _patched(K_BY_ID["dedupe"], "plan", plan)


MUTANTS: list[Mutant] = [
    Mutant("dedupe-by-name-not-hash",
           "去重从「按内容哈希」改成「按文件名 stem」",
           ("lookalike-same-name-diff-bytes",),
           "同 stem 但内容不同的两版文件被当成重复 -> 该用例变红"),
    Mutant("dedupe-recurses-into-subdirs",
           "去重从「只看顶层」改成「递归进子目录」",
           ("lookalike-cache-dir",),
           "cache/ 与 temp/ 里的用户数据被纳入 -> 该用例变红"),
    Mutant("settle-always-true",
           "_settled 恒为 True（删掉 settle 等待）",
           ("unsaved-active-edit",),
           "settle 窗口失效 -> unsaved-active-edit 变红"),
    Mutant("daily-cap-off",
           "actions_today 恒为 -1（每日上限失效）",
           ("limit-daily-cap",),
           "上限失效 -> limit-daily-cap 变红"),
    Mutant("quiet-hours-off",
           "in_quiet 恒为 False（静默时段失效）",
           ("limit-quiet",),
           "静默失效 -> limit-quiet 变红"),
    Mutant("kill-switch-ignored",
           "Sprite.killed 恒为 False（KILL 开关失效）",
           ("limit-kill",),
           "KILL 失效 -> limit-kill 变红"),
    Mutant("allow-overwrite",
           "_check 去掉「目标已存在就拒绝」",
           ("lookalike-quarantine-clash",),
           "允许覆盖 -> 隔离区同名冲突不再被拒，该用例变红"),
    Mutant("empty-dir-check-off",
           "FillNewSeriesDir 不再要求目标目录为空",
           ("inuse-series-nonempty",),
           "非空目录也被补结构 -> inuse-series-nonempty 变红"),
]


# ------------------------------------------------------------------ 应用变异
def _apply(mut: Mutant):
    i = mut.id
    if i == "dedupe-by-name-not-hash":
        return _m_dedupe_group_by_name()
    if i == "dedupe-recurses-into-subdirs":
        return _m_dedupe_recurses()
    if i == "settle-always-true":
        return _m_settled_true()
    if i == "daily-cap-off":
        return _m_cap_off()
    if i == "quiet-hours-off":
        return _m_quiet_off()
    if i == "kill-switch-ignored":
        return _m_kill_off()
    if i == "allow-overwrite":
        return _m_check_no_exists()
    if i == "empty-dir-check-off":
        return _patched(C.FillNewSeriesDir, "plan", _plan_ignore_nonempty)
    raise ValueError(i)


def _plan_ignore_nonempty(self, root, target=None, **kw):
    """去掉「目录必须为空」判断的 FILL 计划。"""
    import re
    t = root / target
    m = re.match(r"^(.*?)(\d+)$", t.name)
    if not (t.is_dir() and m and m.group(1)):
        return []
    prev = [d for d in t.parent.iterdir()
            if d.is_dir() and d != t and (mm := re.match(r"^(.*?)(\d+)$", d.name))
            and mm.group(1) == m.group(1) and int(mm.group(2)) < int(m.group(2))]
    if not prev:
        return []
    last = max(prev, key=lambda d: int(re.search(r"(\d+)$", d.name).group(1)))
    rel = t.relative_to(root)
    ops = [dict(op="mkdir", dst=str(rel / s.name))
           for s in sorted(last.iterdir()) if s.is_dir() and not s.name.startswith(("_", "."))]
    ops.append(dict(op="write", dst=str(rel / "README.md"), content=f"# {t.name}\n\nmutant\n"))
    return ops


# ------------------------------------------------------------------ 跑
def _sig(ids):
    """跑用例，返回 {id: 违规条数}。

    比较**违规条数**而不是 pass/fail：有些用例在基线上本来就是红的
    （已知 bug），变异体没法让它「更红」，但如果违规变多了，同样说明
    变异体确实加重了问题——那也算抓到。
    """
    out = {}
    for cid in ids:
        c = EC.by_id().get(cid)
        if c is None:
            out[cid] = None
            continue
        out[cid] = len(EC.run_case(c).violations)
    return out


def run_mutants(verbose=False):
    rows = []
    for mut in MUTANTS:
        before = _sig(mut.cases)
        with _apply(mut):
            after = _sig(mut.cases)
        worse = sorted(k for k, v in after.items()
                       if v is not None and before.get(k) is not None and v > before[k])
        rows.append(dict(mutant=mut, caught=bool(worse), newly_red=worse,
                         before=before, after=after))
        if verbose:
            print(f"  {'CAUGHT' if worse else 'SURVIVED'} {mut.id}")
            print(f"      before={before}")
            print(f"      after ={after}")
    return rows, [r["mutant"].id for r in rows if not r["caught"]]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    verbose = "-v" in argv or "--verbose" in argv
    print("变异检查：故意改坏安全机制，确认 eval 会抓到（抓不到 = 用例有缺口）\n")
    rows, survived = run_mutants(verbose)
    for r in rows:
        m = r["mutant"]
        print(f"{'CAUGHT' if r['caught'] else 'SURVIVED':9} {m.id:24} {m.desc}")
        print(f"          {m.expect}")
        if r["caught"]:
            print(f"          实际变红: {', '.join(r['newly_red'])}")
    print()
    print(f"变异体 {len(rows)}  抓到 {sum(1 for r in rows if r['caught'])}  漏网 {len(survived)}")
    if survived:
        print("漏网说明用例集有缺口，需补用例：")
        for s in survived:
            print("  -", s)
        return 1
    print("全部变异体都被抓到：用例集对这些机制有约束力。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())