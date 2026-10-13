"""对抗用例库与不变量检查（T8）。

只做两件事：

1. 造场景：把「看起来像可以被自动处理、但其实动不得」的用户数据摆出来，
   让小精灵跑真实 tick 循环（真代码路径，不 mock）。
2. 判结果：跑完检查一组**与实现无关**的不变量，违反就是误操作。

设计原则（对应 TASKS.md 全局规则 2「宁可漏做，不可错做」）：
  - 「动了不该动的」任何时候都算失败，**即使撤销能救回来也算失败**——
    没保存的文档被移动过就是事故，能撤销只是善后。
  - 「该做没做」只在显式声明 expect_action=True 时算失败。否则一个什么都不做的
    精灵也能拿满分，闸门就废了。

用例来源标注在每条的 provenance 字段：
  win  = Windows 真实行为/命名习惯（资源管理器、Office 锁文件、浏览器下载）
  pat  = 通用桌面文件命名习惯（最终/副本/新建/备份…）
  proj = 本项目 README/测试里已写明的约定
数据是合成的，不是从真实用户机器采集的。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sprite.core import Sprite  # noqa: E402
from sprite import config as _cfgmod  # noqa: E402

# 固定基准时间，用例不依赖真实时间（2026-01-01 00:00:00 UTC）
T0 = 1767225600.0

RISKS = [
    "unsaved",   # 没保存的文档 / 正在编辑的文件
    "lookalike", # 看起来像缓存/垃圾、其实是用户数据
    "inuse",     # 正在被使用的目录
    "escape",    # 越出监控目录 / 路径安全
    "limits",    # 开关与上限（KILL / 静默 / 每日上限）
    "undo",      # 撤销与可还原
    "positive",  # 该做就要做（防止「什么都不做」骗到 0 误操作）
]


# --------------------------------------------------------------- 场景小工具
def put(p: Path, text: str, age: float = 1000.0, base: float = T0) -> Path:
    """造一个「已经放凉」的文件（mtime = base - age）。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    os.utime(p, (base - age, base - age))
    return p


def put_bytes(p: Path, data: bytes, age: float = 1000.0, base: float = T0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    os.utime(p, (base - age, base - age))
    return p


def _norm(s) -> str:
    return str(s).replace("\\", "/")


def fs_case_insensitive() -> bool:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "Foo").write_text("x", encoding="utf-8")
        return (Path(d) / "foo").exists()


def snap(root: Path) -> dict:
    """目录内容指纹快照（含目录本身，键统一正斜杠）。"""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_dir():
            out[_norm(p.relative_to(root))] = ("d", None)
        else:
            out[_norm(p.relative_to(root))] = ("f", hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def mtimes(root: Path) -> dict:
    out = {}
    for p in Path(root).rglob("*"):
        if p.is_file():
            try:
                out[_norm(p.relative_to(root))] = p.stat().st_mtime
            except OSError:
                pass
    return out


def _age_all(root: Path, now: float, age_by) -> None:
    if age_by is None:
        return
    for p in Path(root).rglob("*"):
        if p.is_file():
            try:
                os.utime(p, (now - age_by, now - age_by))
            except OSError:
                pass


def _ops_of(msg: dict) -> list:
    j = msg.get("journal")
    if not j or not Path(j).exists():
        return []
    try:
        return json.loads(Path(j).read_text("utf-8")).get("ops", [])
    except Exception:
        return []


def _diff(before: dict, after: dict) -> str:
    gone = sorted(k for k in before if k not in after)
    new = sorted(k for k in after if k not in before)
    chg = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    parts = []
    if gone:
        parts.append(f"消失={gone}")
    if new:
        parts.append(f"多出={new}")
    if chg:
        parts.append(f"内容变了={chg}")
    return "；".join(parts) or "（无差异）"


# --------------------------------------------------------------- 用例定义
@dataclass
class Case:
    id: str
    risk: str
    title: str
    provenance: str
    build: Callable[[Path], dict]                  # 造初始数据 -> {"protected": [...]}
    rules: tuple = ()
    trigger: Callable[[Path], None] | None = None  # 基线之后用户做的事
    prepare: Callable[[Path, Path], None] | None = None  # 造 home（KILL 等）
    cfg_over: dict = field(default_factory=dict)
    ticks: int = 6
    step_s: float = 180.0            # 每个 tick 推进的虚拟秒数
    age_by: float | None = 1000.0    # 每 tick 后把 mtime 往前推，模拟「放凉」
    expect_action: bool = False
    protected: tuple = ()            # 绝不能出现在任何 op 里的路径
    post: Callable[[Path, list], list] | None = None
    notes: str = ""


@dataclass
class Result:
    case: Case
    violations: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return not self.violations and not self.skipped

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.ok else "FAIL"


def run_case(c: Case) -> Result:
    tmp = Path(tempfile.mkdtemp(prefix="ol_eval_"))
    try:
        return _run(c, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(c: Case, tmp: Path) -> Result:
    root, outside, home = tmp / "root", tmp / "outside", tmp / "home"
    for d in (root, outside, home):
        d.mkdir(parents=True)
    (outside / "SENTINEL.txt").write_text("这一整个目录都不该被碰", encoding="utf-8")
    outside_before = snap(outside)

    info = c.build(root) or {}
    protected = {_norm(p) for p in info.get("protected", [])} | {_norm(p) for p in c.protected}

    cfg = json.loads(json.dumps(_cfgmod.DEFAULTS))
    cfg["quiet_hours"] = None
    cfg["watch"] = {str(root): list(c.rules)}
    cfg.update(c.cfg_over)

    if c.prepare:
        c.prepare(root, home)

    clock = [T0]
    sprite = Sprite(cfg, home, clock=lambda: clock[0])
    sprite.tick()                        # 基线：第一次只建快照，不动手
    if c.trigger:
        c.trigger(root)

    before = snap(root)
    settle = cfg["settle_s"]
    actions: list = []
    violations: list = []
    touched: set = set()

    for _ in range(c.ticks):
        now = clock[0]
        mt = mtimes(root)
        for m in sprite.tick():
            if m.get("kind") != "action":
                continue
            actions.append(m)
            ops = _ops_of(m)
            for o in ops:
                for k in ("src", "dst"):
                    if o.get(k):
                        touched.add(_norm(o[k]))
            # 不变量 I3：不能动还在 settle 窗口里的文件
            for o in ops:
                src = _norm(o.get("src") or "")
                if src and src in mt and (now - mt[src]) < settle:
                    violations.append(
                        f"动了还在 settle 窗口内的文件：{src}"
                        f"（age={now - mt[src]:.0f}s < settle_s={settle}s）")
        clock[0] += c.step_s
        _age_all(root, clock[0], c.age_by)

    # 不变量 I2：监控目录之外一个字节都不能变
    if snap(outside) != outside_before:
        violations.append("动了监控目录之外的路径（outside/SENTINEL.txt 变了或旁边多了东西）")

    # 不变量 I5：受保护路径一次都不能出现在 op 里（哪怕最后撤销回来了）
    hit = sorted(protected & touched)
    if hit:
        violations.append(f"动了受保护的路径：{hit}（撤销能救回来也算事故）")

    # 场景专属断言必须在**动手之后、撤销之前**跑：它要看的是「做完什么样」，
    # 不是「撤销后回到什么样」。放在撤销之后跑会把成功的动作误判成没做。
    if c.post:
        violations += c.post(root, actions)

    # 不变量 I1：撤销所有动作后，目录必须逐字节回到动手前
    for m in actions:
        if not sprite.undo(m["id"]):
            violations.append(f"撤销失败：{m['id']}")
    after = snap(root)
    if after != before:
        violations.append("撤销全部动作后目录没有回到原样：" + _diff(before, after))

    if c.expect_action and not actions:
        violations.append("该动手的场景却一次都没动手（漏做也要被记录）")
    if not c.expect_action and actions:
        violations.append(f"不该动手的场景却动了 {len(actions)} 次：" +
                          "、".join(m.get("text", "")[:30] for m in actions))

    return Result(c, violations, actions)


# --------------------------------------------------------------- 用例集
def _mk(*fns):
    """把多个造数据的函数合成一个 build（返回 {} 表示无受保护路径）。"""
    def build(r):
        for fn in fns:
            fn(r)
        return {}
    return build


def _put(rel, text, age=1000.0):
    def fn(r):
        put(r / rel, text, age=age)
    return fn


def _mkdir(rel):
    def fn(r):
        (r / rel).mkdir(parents=True, exist_ok=True)
    return fn


def _dl_build(r):
    """基线：下载夹里已有一个原件（放凉 5000 秒，确保它比后续副本旧）。"""
    put(r / "paper.pdf", "REALPAPER", age=5000)
    return {}


def _dl_trig(r):
    """用户又下了一次同样的文件。

    刻意**不**重写原件：真实情况下重新下载不会改动已有文件的 mtime，
    新副本才是新的那个。DownloadDedupe 按 mtime 排序并保留最旧的一个，
    所以原件应当留下、新副本进 _dupes。
    """
    put(r / "paper (1).pdf", "REALPAPER", age=1000)


_DL = (_dl_build, _dl_trig)


CASES: list[Case] = [
    # ================= 没保存的文档 =================
    Case("unsaved-open-doc", "unsaved",
         "Word 里打开着的文档不能被改名（~$ 锁文件存在即证明它开着）",
         "win: Word/WPS 打开文档时生成 ~$xxxx 锁文件，文档本体被 Office 独占打开",
         lambda r: {"protected": ["~$报告.docx"]},
         ("versioning", "dedupe"),
         lambda r: [put(r / "~$报告.docx", "OFFICE LOCK"),
                    put(r / "报告.docx", "v1"),
                    put(r / "报告_最终.docx", "v2"),
                    put(r / "报告_最终(1).docx", "v3")],
         protected=("~$报告.docx",),
         notes="snapshot() 跳过 ~$ 文件，所以精灵看不见「这个文档正开着」这个事实。"),

    Case("unsaved-active-edit", "unsaved",
         "刚下载完（<settle_s）的重复文件不能立刻动",
         "proj: 配置里的 settle_s=60",
         _mk(_put("草稿.md", "old", age=3000)),
         ("dedupe", "versioning"),
         lambda r: [put(r / "草稿_最终.md", "SAME", age=5),
                    put(r / "草稿_最终(1).md", "SAME", age=5)],
         protected=("草稿_最终.md", "草稿_最终(1).md"),
         ticks=1, step_s=5,          # 只看第一个 tick：此刻 age=5s < settle_s=60
         notes="必须只跑 1 个 tick 且不推进时钟——settle 是时间窗口，多跑几轮文件自然放凉。"
               "对照组 settle-dedupe 证明放凉后确实会动手，两条一起证明 settle 有牙。"),

    Case("unsaved-inprogress-download", "unsaved",
         "浏览器没下完的 .part 分片不能被搬走",
         "win: Chrome/Edge 下载中写 .part/.crdownload，同时存在同名 .zip",
         _mk(),
         ("dedupe",),
         lambda r: [put(r / "big.zip", "PAYLOAD" * 8),
                    put(r / "big.zip.part", "PAYLOAD" * 8)],
         protected=("big.zip.part",),
         notes="snapshot() 正确跳过了 .part，但 dedupe 用的 _files() 是另一套过滤条件。"),

    # ================= 看起来像缓存的用户数据 =================
    Case("lookalike-cache-dir", "lookalike",
         "叫 cache/temp 的目录里装的是用户数据，不能碰",
         "pat: 用户拿 cache 当项目名，不是真的缓存",
         lambda r: {"protected": ["cache/我的笔记.txt", "temp/合同草稿.docx"]},
         ("dedupe", "versioning", "scaffold"),
         lambda r: [put(r / "cache" / "我的笔记.txt", "NOTE"),
                    put(r / "temp" / "合同草稿.docx", "CONTRACT"),
                    put(r / "cache" / "我的笔记 (1).txt", "NOTE"),
                    # 顶层也放一对真重复：dedupe 只有在顶层有事件时才会被提出，
                    # 没有顶层文件的话规则根本不会被调用，这条就测不到「不递归」了。
                    # 原件必须明显更旧——mtime 相同时 dedupe 会退化成按文件名排序，
                    # "real (1).pdf" 字典序在 "real.pdf" 之前，保留的就变成副本了。
                    put(r / "real.pdf", "TOPLEVEL", age=5000),
                    put(r / "real (1).pdf", "TOPLEVEL", age=1000)],
         protected=("cache/我的笔记.txt", "temp/合同草稿.docx"),
         expect_action=True,
         post=lambda root, acts: ([] if (root / "real.pdf").exists()
                                  else ["顶层原件 real.pdf 必须留在原地"]),
         notes="顶层真重复该被去重（动作合法），但 cache/ 与 temp/ 里的用户数据"
               "一次都不能出现在 op 里。这条同时钉死「只看顶层」这个前提。"),

    Case("lookalike-quarantine-clash", "lookalike",
         "隔离区里已有同名同内容文件时必须整体拒绝",
         "proj: 全局规则 2「不认识的一律当唯一物，不碰」",
         _mk(_put("a.pdf", "SAME", age=5000),
             _mkdir("_dupes"),
             _put("_dupes/b.pdf", "SAME", age=5000)),
         ("dedupe",),
         lambda r: [put(r / "b.pdf", "SAME", age=5)]),

    Case("lookalike-zero-byte", "lookalike",
         "空文件不能被当成重复文件搬走",
         "win: 0 字节文件是占位符，sha256 恒等",
         _mk(),
         ("dedupe",),
         lambda r: [put_bytes(r / "empty1.txt", b""),
                    put_bytes(r / "empty2.txt", b""),
                    put_bytes(r / "empty3.log", b"")],
         notes="所有空文件 sha256 相同，按内容分组必然误判。"),

    Case("lookalike-cross-type", "lookalike",
         "同字节但不同类型/用途的文件不算重复",
         "pat: 合同.pdf 与 备份说明.txt 同内容但语义完全不同",
         _mk(),
         ("dedupe",),
         lambda r: [put(r / "合同.pdf", "IMPORTANT"),
                    put(r / "备份说明.txt", "IMPORTANT")],
         protected=("备份说明.txt",),
         notes="DownloadDedupe 只按 sha256 分组，扩展名与文件名完全不参与判断。"),

    Case("lookalike-same-name-diff-bytes", "lookalike",
         "同名同后缀但内容不同的两个文件不是重复",
         "pat: 报告.docx 与 报告(1).docx 是用户改过的两版，不是重复下载",
         _mk(),
         ("dedupe",),
         lambda r: [put(r / "报告.docx", "FIRST VERSION"),
                    put(r / "报告(1).docx", "SECOND VERSION")],
         protected=("报告(1).docx",),
         notes="按内容分组时两者哈希不同 -> 不动。这条把「必须按内容而不是按名字去重」"
               "钉死：换成按名字分组的实现会立刻变红。"),

    # ================= 正在被使用的目录 =================
    Case("inuse-series-src", "inuse",
         "搭新目录时只能读上一期的结构，不能写上一期",
         "proj: FillNewSeriesDir.plan 读上一期子目录名",
         _mk(_put("lab6/data/a.csv", "x", age=3000),
             _put("lab6/figs/f.png", "y", age=3000)),
         ("scaffold",),
         lambda r: [put(r / "lab6" / "data" / "b.csv", "y", age=5),
                    (r / "lab7").mkdir()],
         protected=("lab6/data/a.csv", "lab6/figs/f.png", "lab6/data/b.csv"),
         expect_action=True,
         notes="scaffold 允许动手（lab7 是空的、且只写 lab7），但 lab6 一个字节都不能变。"),

    Case("inuse-series-nonempty", "inuse",
         "新建的编号目录里已经有东西了 -> 不许补结构",
         "proj: FillNewSeriesDir.plan 要求目标目录为空",
         _mk(_put("lab6/data/a.csv", "x", age=3000)),
         ("scaffold",),
         # lab7 必须在基线**之后**创建：scaffold 只在事件流里看到「新建的编号目录」
         # 时才触发（core.py propose 第 77 行）。基线里就建好= 根本没有事件，
         # 测不到plan 里的空目录判断。
         lambda r: [(r / "lab7").mkdir(), put(r / "lab7" / "already.csv", "用户自己放的", age=5)],
         protected=("lab7/already.csv",)),

    # ================= 开关与上限 =================
    Case("limit-kill", "limits", "KILL 开关存在时一次都不能动手",
         "proj: __main__.py --kill",
         _DL[0], ("dedupe",), _DL[1],
         prepare=lambda root, home: (home / "KILL").write_text("stop"),
         expect_action=False),

    Case("limit-daily-cap", "limits", "每日上限为 0 时一次都不能动手",
         "proj: 配置 daily_cap",
         _DL[0], ("dedupe",), _DL[1], cfg_over={"daily_cap": 0}),

    Case("limit-quiet", "limits", "静默时段内只攒着不动手",
         "proj: 配置 quiet_hours 23:00-08:00",
         _DL[0], ("dedupe",), _DL[1],
         cfg_over={"quiet_hours": ["00:00", "23:59"]}),

    Case("limit-disabled", "limits", "配置里 enabled=false 时一次都不能动手",
         "proj: Sprite.killed()",
         _DL[0], ("dedupe",), _DL[1], cfg_over={"enabled": False}),

    Case("limit-ops-cap", "limits", "单次动作的操作数上限真的生效",
         "proj: 配置 max_ops_per_action",
         _mk(*[_put("f%d.txt" % i, "SAME") for i in range(12)]),
         ("dedupe",), lambda r: [put(r / ("f%d.txt" % i), "SAME", age=2000) for i in range(12)],
         cfg_over={"max_ops_per_action": 2},
         expect_action=False,
         notes="12 个重复文件会产生 11 个 move，超过上限 2，必须整体拒绝而不是截断执行。"),

    # ================= 撤销 =================
    Case("undo-byte-exact", "undo", "下载去重撤销后逐字节回到原样，且原件留在原地",
         "proj: 全局规则 2「任何删除都不能真删」",
         _DL[0], ("dedupe",), _DL[1], expect_action=True,
         post=lambda root, acts: ([] if (root / "paper.pdf").exists()
                                  else ["原件 paper.pdf 必须留在原地"])),

    Case("undo-versioning", "undo", "版本化撤销后逐字节回到原样",
         "pat: 最终/副本 命名堆",
         _mk(_put("报告.docx", "v1", age=3000),
             _put("报告_最终.docx", "v2", age=2000),
             _put("报告_最终(1).docx", "v3", age=2000)),
         ("versioning",), None, expect_action=True),

    # ================= 该做就要做 =================
    Case("positive-dedupe", "positive",
         "真正重复的下载文件应该被移进 _dupes，且原件留下",
         "win: 浏览器重复下载同名文件",
         _DL[0], ("dedupe",), _DL[1], expect_action=True,
         post=lambda root, acts: ([] if (root / "paper.pdf").exists()
                                  else ["原件 paper.pdf 必须留在原地"])),

    Case("settle-dedupe", "positive",
         "同一批重复文件放凉之后就该动手（证明 settle 只是延迟、不是永久挡住）",
         "proj: settle_s 只延迟不取消",
         _DL[0], ("dedupe",), _DL[1], expect_action=True,
         notes="与 unsaved-active-edit 构成一对：一起证明 settle 窗口既拦得住、也放得开。"),

    Case("positive-versioning", "positive", "四个同 stem 的报告应该被编成 v01..v04",
         "pat: 最终/副本/最终版",
         _mk(_put("报告.docx", "v1", age=3000),
             _put("报告_最终.docx", "v2", age=2000),
             _put("报告_最终(1).docx", "v3", age=2000),
             _put("报告_最终版.docx", "v4", age=2000)),
         ("versioning",), None, expect_action=True),

    Case("positive-scaffold", "positive", "空的编号目录应该被补齐结构",
         "proj: FillNewSeriesDir",
         _mk(_put("lab6/data/a.csv", "x", age=3000)),
         ("scaffold",), lambda r: [(r / "lab7").mkdir()],
         expect_action=True,
         post=lambda root, acts: ([] if (root / "lab7" / "data").is_dir()
                                  else ["lab7/data 应该被建出来"])),
]


# --------------------------------------------------------------- 引擎层守卫
def guard_no_escape():
    """catalog._check 必须拒绝任何越出 root 的路径。"""
    from lookout.insight.closed_loop import catalog as K
    v = []
    tmp = Path(tempfile.mkdtemp(prefix="ol_guard_"))
    try:
        (tmp / "inside.txt").write_text("x", encoding="utf-8")
        for bad in (dict(op="write", dst="../evil.txt", content="x"),
                    dict(op="write", dst="sub/../../evil.txt", content="x")):
            try:
                K._check(tmp, [bad])
                v.append(f"_check 放过了越界路径：{bad['dst']}")
            except K.PlanError:
                pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return v


def guard_no_overwrite():
    """catalog._check 必须拒绝覆盖已存在的文件。"""
    from lookout.insight.closed_loop import catalog as K
    v = []
    tmp = Path(tempfile.mkdtemp(prefix="ol_guard_"))
    try:
        (tmp / "a.txt").write_text("orig", encoding="utf-8")
        try:
            K._check(tmp, [dict(op="write", dst="a.txt", content="new")])
            v.append("_check 放过了覆盖已有文件：a.txt")
        except K.PlanError:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return v


def guard_no_delete_op():
    """全局规则 2：没有 delete 操作。"""
    from sprite.core import SAFE_OPS, policy_check, Refused
    v = []
    if "delete" in SAFE_OPS:
        v.append(f"SAFE_OPS 里出现了 delete：{sorted(SAFE_OPS)}")
        return v
    tmp = Path(tempfile.mkdtemp(prefix="ol_guard_"))
    try:
        try:
            policy_check(tmp, [dict(op="delete", dst="x")], {"max_ops_per_action": 30})
            v.append("policy_check 放过了 delete 操作")
        except (Refused, Exception):
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return v


def guard_dry_run_is_pure():
    """dry_run 绝对不能改磁盘。"""
    from lookout.insight.closed_loop import catalog as K
    v = []
    tmp = Path(tempfile.mkdtemp(prefix="ol_guard_"))
    try:
        (tmp / "a.pdf").write_text("SAME", encoding="utf-8")
        (tmp / "b.pdf").write_text("SAME", encoding="utf-8")
        before = snap(tmp)
        item = K.BY_ID["dedupe"]
        item.dry_run(tmp)
        if snap(tmp) != before:
            v.append("DownloadDedupe.dry_run 改动了磁盘")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return v


def guard_undo_is_exact():
    """execute -> undo 必须逐字节还原。"""
    from lookout.insight.closed_loop import catalog as K
    v = []
    tmp = Path(tempfile.mkdtemp(prefix="ol_guard_"))
    try:
        (tmp / "a.pdf").write_text("SAME", encoding="utf-8")
        (tmp / "b.pdf").write_text("SAME", encoding="utf-8")
        before = snap(tmp)
        j = tmp / "j.json"
        K.execute(tmp, K.BY_ID["dedupe"].plan(tmp), j)
        if snap(tmp) == before:
            v.append("execute 之后目录没变化，去重根本没执行")
        K.undo(j)
        if snap(tmp) != before:
            v.append("undo 之后没有逐字节还原：" + _diff(before, snap(tmp)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return v


def guard_snapshot_skips_lockfiles():
    """snapshot() 必须跳过 ~$ 与临时后缀，否则 Office 锁文件会混进事件流。"""
    from sprite.core import snapshot
    v = []
    tmp = Path(tempfile.mkdtemp(prefix="ol_guard_"))
    try:
        for n in ("~$a.docx", "b.tmp", "c.crdownload", "d.part", "real.txt"):
            (tmp / n).write_text("x", encoding="utf-8")
        keys = set(snapshot(tmp, 2))
        for n in ("~$a.docx", "b.tmp", "c.crdownload", "d.part"):
            if n in keys:
                v.append(f"snapshot() 没有跳过 {n}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return v


GUARDS = [
    ("engine-no-escape", guard_no_escape),
    ("engine-no-overwrite", guard_no_overwrite),
    ("engine-no-delete-op", guard_no_delete_op),
    ("engine-dry-run-pure", guard_dry_run_is_pure),
    ("engine-undo-exact", guard_undo_is_exact),
    ("engine-snapshot-skips-lockfiles", guard_snapshot_skips_lockfiles),
]


def run_guards() -> list:
    out = []
    for name, fn in GUARDS:
        try:
            out.append((name, fn()))
        except Exception as e:                       # noqa: BLE001
            out.append((name, [f"守卫自身抛异常：{type(e).__name__}: {e}"]))
    return out


def by_id() -> dict:
    return {c.id: c for c in CASES}


def select(ids=None, risk=None) -> list:
    out = CASES
    if ids:
        want = set(ids)
        out = [c for c in out if c.id in want]
    if risk:
        out = [c for c in out if c.risk == risk]
    return out