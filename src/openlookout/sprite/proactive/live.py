"""小精灵实时窗口 + 热更新。
python -m sprite.proactive.live          启动：采集 + 理解 + 窗口，三个子进程由它管理
- 窗口（小猫气泡）显示最新一条“你在做什么”，来自 perceive/current.json。
- 监视 sprite/proactive/*.py 和 sprite/gui.py：任何一个改动，自动重启全部子进程（热更新）。
- 子进程退出会自动拉起。所有事件写入 perceive/supervisor.log。
"""
from __future__ import annotations
import json, os, subprocess, sys, threading, time
from datetime import datetime
from pathlib import Path

from .perceive import DIR, NOW
from .feedback import add_feedback
from .help import OFFER_OPTIONS
from . import conversation

ROOT = Path(__file__).resolve().parents[2]                       # src/openlookout
# 同意门（2026-10-13）：offer 是要动手改电脑的提议，**必须用户点头才执行**。
# 这句话原本是「不等待用户确认」——offer 记录在 GUI tick 里被直接 auto_started，
# 320 条 offers.jsonl 里 accepted/rejected 各 0 次、54 次 auto_started 就是这么来的，
# 连 gui.py 里画「好的/不用」的分支都从没被走到过。
# 改成必须点头之后，真正会改机器的动作只剩两条路，都留下了账：
#   1) 用户点了「好的」→ run_offer（actions.py 每个工具都先写 undo 日志）；
#   2) brain 自己的常驻观察循环（走 desktop_* 工具，不经过 offer）。
# 代价见交付说明：brain 那条路本来就不经过 offer，同意门管不到它。
OFFER_GOAL = ("小精灵已经决定主动替用户处理这件事：「{text}」。请你现在就自己判断怎么帮他做，用合适的办法。"
              "原则：不绕过安全检查，不删除文件，不结束用户正在用的程序；每个会改变电脑的操作，先记录撤回方法。"
              "只做安全、可撤回的动作。做完用一句温和的话报告做了什么。")


def _last_json(stdout: str) -> dict | None:
    """cli 最后打印的是一个多行 JSON 对象，从最后一个顶层 '{' 开始解析。"""
    if not isinstance(stdout, str) or not stdout.strip():
        return None
    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    for idx, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[idx:])
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        return None
    def score(value: dict) -> tuple[int, int]:
        keys = set(value)
        # The outer run_task result has these fields; nested tool payloads
        # generally have only ``text``/``success``.
        weight = sum(
            amount for key, amount in {
                "objective": 8, "answered": 6, "actions": 5,
                "action_results": 5, "report": 4, "final": 3,
            }.items() if key in keys
        )
        return weight, candidates.index(value)
    return max(candidates, key=score)


INSPECTION_TOOLS = {
    "desktop_processes",
    "desktop_inventory",
    "desktop_provider_probe",
    "basic_time",
    "basic_calculate",
    "basic_weather",
    "basic_location",
    "basic_search",
    "basic_web_search",
    "basic_web_read",
}


def _successful_action(result: dict) -> dict | None:
    """Return the last successful mutating desktop action, if present."""
    rows = result.get("action_results")
    if not isinstance(rows, list):
        return None
    for row in reversed(rows):
        if isinstance(row, dict) and row.get("success") and row.get("tool") not in INSPECTION_TOOLS:
            return row
    return None


def _successful_mutation_count(result: dict) -> int:
    """成功改动了电脑的动作数（只读工具不算）。终态行据此说明「到底动没动过机器」。"""
    rows = result.get("action_results")
    if not isinstance(rows, list):
        return 0
    return sum(1 for row in rows
               if isinstance(row, dict) and row.get("success") and row.get("tool") not in INSPECTION_TOOLS)


def run_offer(offer: dict, show) -> None:
    """交给 VISTA 桌面任务立即执行，并把真实结果放进气泡。

    终态词表（2026-10-12 审计后修正，见 docs/AUTO_ACTION_OUTCOME_AUDIT.md）：

    * ``auto_completed``  运行自己报告 ``answered=True``：提交了最终结论；
    * ``auto_no_answer``  进程正常退出，但这一段运行没有提交最终结论
      （旧词 ``auto_failed`` 的真实含义——它的名字和语义是反的）；
    * ``auto_errored``    进程非 0 退出；
    * ``auto_failed``     保留给真正的启动失败 / 超时，不再表示「没提交结论」。

    判据用运行自己报告的 ``answered``，不是「final 文本是否为空」：``answered`` 与运行归档的
    ``closed.status=completed`` 可证明等价（session.submit→finished=True→runtime.py 置
    COMPLETED；否则 close()→stop("session_closed")→stopped），账本与证据因此按构造一致。
    ``report`` 在没提交结论时保存运行自己的留言（若有），否则给一句与机器改动数一致的话。
    """
    goal = OFFER_GOAL.format(text=offer.get("text", ""))
    run_dir = DIR.parent / "desktop_runs" / time.strftime("%Y%m%d-%H%M%S")
    try:
        proc = subprocess.run([sys.executable, "-m", "vista.benchmarks.desktop.cli",
                               "--objective", goal, "--directory", str(run_dir)],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        result = _last_json(proc.stdout) or {}
    except subprocess.TimeoutExpired:
        record_offer_result(offer, "auto_failed", report="这件事处理超时，我没有留下半截改动。",
                            run_dir=str(run_dir))
        show(dict(kind="say", text="这件事花的时间有点长，我先停下了，没有留下半截改动。")); return
    except Exception as exc:
        record_offer_result(offer, "auto_failed", error=type(exc).__name__,
                            report="这次处理没有启动成功，电脑没有被改动。", run_dir=str(run_dir))
        show(dict(kind="say", text="这次处理没有启动成功，电脑没有被改动。")); return
    action = _successful_action(result)
    # Persistent VISTA turns end at companion, so ``final`` is often empty.
    # A post-action report (or successful mutating tool) is the completion
    # signal for an accepted offer.
    submitted = str(result.get("final") or "").strip()
    report = str(result.get("report") or "").strip()
    final = submitted or ((report or str(action.get("text") or "").strip()) if action else "")
    mutations = _successful_mutation_count(result)
    answered = bool(result.get("answered")) or bool(submitted)
    common = dict(run_dir=str(run_dir), mutations=mutations)
    if proc.returncode:
        record_offer_result(offer, "auto_errored", error=f"returncode:{proc.returncode}", **common,
                            report="这次处理出错了，我没有留下半截改动。")
        show(dict(kind="say", text="这次处理出错了，我没有留下半截改动。")); return
    if not answered:
        error = "no_final_answer"
        if result.get("failure"):
            error += f";failure:{result['failure']}"
        if report:
            note = report[:300]
        elif mutations:
            note = f"这次处理没走到最后一步，我先停下了；已经做了 {mutations} 处可撤回的改动。"
        else:
            note = "这次处理没走到最后一步，我先停下了，没有改动电脑。"
        record_offer_result(offer, "auto_no_answer", error=error, report=note, **common)
        show(dict(kind="say", text=note)); return
    if not final:
        final = report or "已经处理完成。"
    record_offer_result(offer, "auto_completed", report=final[:300], **common)
    show(dict(kind="action", text=final[:300], action_id=offer.get("id") or "help"))


def run_risk_batch(offer: dict, show) -> None:
    """执行已批准的风险分级批次：只做提议里列出的那几条。

    与 `run_offer` 的区别是这里**不再起一次模型运行**。用户点头批准的是那份
    具体清单（3 份交付物），所以执行的就该是那 3 份；再让模型自己决定一遍，
    批准范围就变了。TTL 过期在这里被 `permissions.execute` 挡住，一条都不做。
    """
    from vista.benchmarks.desktop import permissions

    results = permissions.execute(offer)
    ok = [r for r in results if r.get("success")]
    bad = [r for r in results if not r.get("success")]
    report = _batch_report(results)
    record_offer_result(offer, "auto_completed" if ok and not bad else "auto_no_answer",
                        mutations=len(ok), items=len(results), report=report)
    if not ok or bad:
        show(dict(kind="say", text=report))
        return
    show(dict(kind="action", text=report, action_id=offer.get("id") or "batch"))


def _batch_report(results: list[dict]) -> str:
    ok = sum(1 for r in results if r.get("success"))
    total = len(results)
    if ok == total:
        return f"按你的同意做了 {total} 件事，随时可以撤回。"
    if ok:
        # 部分失败必须说清「做了几件、没做几件」，不能笼统说完成。
        return f"{total} 件事里做成了 {ok} 件，其余没做成；我没有多做别的。"
    return "这一批没有做成，电脑状态没有被改动。"


def undo_offer() -> str:
    """撤回 Claude Code 在这次帮忙里记录的所有操作。"""
    code = "from vista.benchmarks.desktop.actions import undo; print(undo({}).text)"
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return (proc.stdout.strip() or "撤回没有成功，我没有改动任何其他东西。")[:300]


PKG = Path(__file__).resolve().parent                      # sprite/proactive
ROOT = Path(__file__).resolve().parents[2]                 # src/openlookout（-m sprite... 的工作目录）
CURRENT = DIR / "current.json"
SUP_LOG = DIR / "supervisor.log"
CHILDREN = {
    "brain": ["-m", "vista.benchmarks.desktop.brain"],
    "gui": ["-m", "sprite.proactive.live", "--gui"],
    "recorder": [str(ROOT.parents[1] / "record_win.py"), "--out", str(DIR / "operations.jsonl"),
                 "--ext-port", "0", "--parent-pid", str(os.getpid()), "--heartbeat", "60"],
}
# 监督循环每 2 秒看一次子进程。旁边曾有一个同样写死的 SHOW_S，是「气泡挂一小时」
# 那个 bug 的源头之一；它早已没有任何调用点，删掉而不是留着继续误导人。
CHECK_S = 2
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
OFFER_MAX_AGE_S = 180
# 带选项的气泡停留时长（秒）。gui.show 对带 options 的气泡会再乘一次系数 2。
# 原来这里的基数是 120，乘 5 之后实际给用户 600s——为了一个「好的/不用」
# 让人等十分钟，等不到就过期作废，等于提议白提。现在基数 60、系数 2，
# 实际 60×2=120s（上一版注释误写成 300s，算术错了，issue #11 新发现 2）：
# 够读完并点头/拒绝，又不至于久到忘了这是在问什么。
OFFER_ASK_S = 60
# 气泡停留时长按内容量给，不给固定值。实测问题：companion 气泡写死 180s、
# 待机提示挂满一小时，用户看到的是「同一句话杵在屏幕上一小时」。
# 一条 60 字的话读完大约 4 秒；给 30s 已经是很宽的余量。
# BUBBLE_READ_S 是基础值，按长度每 10 字再加 1 秒，上限 90s：
# 短句一闪就过，长句留得久一点，不会出现短句霸屏一小时。
BUBBLE_READ_S, BUBBLE_PER_CHAR_S, BUBBLE_MAX_S = 30.0, 0.1, 90.0
# 待机提示文案。这是句引导语，不是精灵对用户说的话——所以 present() 里
# 显式不把它写进对话记录（否则 transcript 里会出现一条它从未说过的发言）。
IDLE_HINT_TEXT = "我在，点我可以直接聊天。"
# 「正在处理」状态最多保持多久（毫秒）。这是一道**状态**上限，不是气泡时长：
# run_offer 允许跑到 900s，在这段时间里 tick 不能把精灵的进度汇报当成新提议
# 重新处理一遍。气泡早已自己消失，但「还在忙」这个事实要留着。
WORKING_GUARD_MS = 900_000


def bubble_seconds(text: str, *, floor: float = BUBBLE_READ_S) -> float:
    """气泡该停留多久：够读完这句话就行，不占着屏幕。"""
    length = len(str(text or ""))
    return max(floor, min(BUBBLE_MAX_S, BUBBLE_READ_S + length * BUBBLE_PER_CHAR_S))


# GUI（热更新/崩溃）重启后，多久以前的 companion 句还允许重新弹一次。
# 旧值在 read_offer() 里写死 900s：任何一次窗口重启都会把 15 分钟内弹过的
# 旧闲聊原样重弹——气泡本体早就消失了，重启却让它「复活」，和「同一句话
# 显示很久」是同一种体验（issue #11 新发现 1）。
# 取舍：重放窗口 = 这句话本来该在屏幕上活的时间（bubble_seconds，30~90s）
# + 一次重启宽限。正常热更新/崩溃拉起只花几秒，当句不会丢；但气泡生命
# 早已结束的旧句不许再弹。刻意不按 900s 对齐 run_offer——那是**执行**预算
# （WORKING_GUARD_MS 守护的「正在处理」状态），与一句闲聊的可读寿命无关。
COMPANION_REPLAY_GRACE_S = 15.0


def companion_max_age_s(offer: dict) -> float:
    """companion 句在 GUI 重启后仍可重放的年龄上限：气泡生命 + 一次重启宽限。"""
    return bubble_seconds(offer.get("text")) + COMPANION_REPLAY_GRACE_S

# 这些状态说明这条 offer 已经有结论了，窗口重启后不许再拿它去问一次。
# 旧的 auto_* 是同意门之前的历史词表，保留是为了让重启判断对老记录仍然成立。
SETTLED_OFFER_STATES = frozenset({
    "started", "expired", "accepted", "rejected", "dismissed", "retracted",
    "auto_started", "auto_completed", "auto_failed", "auto_no_answer",
    "auto_errored", "undone", "undo_requested", "ignored",
    "acknowledged", "responded",
})


_LOG_FAILS = 0


def log(msg: str) -> None:
    """写一行监督日志。**任何写盘失败都不能往上抛。**

    实测事故（10-13 17:06~17:09）：C 盘被填到 0 字节，这一行里的
    SUP_LOG.open() 抛 ENOSPC，异常直接穿过 supervise() 的 finally，
    把 brain / gui / recorder 三个子进程全部 terminate 掉——精灵就这么
    静默死了，日志里连「已停止」都没留下（写那句也失败）。
    用户看到的就是「启动一次说一次话，然后就再也不说了」。

    日志是附属品，精灵不是。所以这里必须吞掉异常：宁可丢一行日志，
    也不能让一次磁盘满把整个陪伴循环带走。

    写盘从失败跳回成功时补一条恢复日志并归零（PR #16 复审 P2-3）：
    pythonw 没有控制台，不补这行的话「之前一直写不进去」永远不可见。
    """
    global _LOG_FAILS
    line = f"{datetime.now():%H:%M:%S} {msg}"
    recovered = 0
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        with SUP_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            if _LOG_FAILS:
                recovered = _LOG_FAILS
                f.write(f"{datetime.now():%H:%M:%S} 监督日志写盘已恢复"
                        f"（此前连续 {recovered} 次失败）\n")
        _LOG_FAILS = 0
    except OSError:
        _LOG_FAILS += 1
    try:
        print(line, flush=True)
        if recovered:
            print(f"{datetime.now():%H:%M:%S} 监督日志写盘已恢复"
                  f"（此前连续 {recovered} 次失败）", flush=True)
    except Exception:
        pass


def watched_stamp() -> float:
    files = list(PKG.glob("*.py")) + list((ROOT / "vista" / "benchmarks" / "desktop").glob("*.py")) + [ROOT / "sprite" / "gui.py"]
    return max((p.stat(). st_mtime for p in files if p.exists()), default=0.0)


def brain_stamp() -> float:
    """只有 brain 自己和它直接依赖的文件变了才值得重启 brain。

    为什么要分开：brain 的价值在于**同一个模型会话持续累积每一帧画面**。
    只有会改变 runtime、工具或提示词的直接依赖才重启；窗口和其它无关文件的
    修改不应杀掉正在积累的视觉上下文。
    """
    d = ROOT / "vista" / "benchmarks" / "desktop"
    files = [d / "brain.py", d / "actions.py", d / "session.py", d / "profiles.py",
             d / "agenda.py", d / "decision_engine.py",
             d / "desktopfacts.py", d / "chat_planner.py", d / "chat_facts.py",
             d / "weather.py", d / "historyfacts.py", PKG / "live.py"]
    # 后端实现也是brain 的一部分，而且它坏掉的方式最隐蔽：改
    # vista/backends/claude/factory.py 让 create_backend 多接一个参数，brain
    # 就会 TypeError -> 静默降级到 direct 端点 -> 每轮 400，但这份列表当时只
    # 盯着 desktop/，改动永远触发不了重启，精灵就这么带着400 跑了几小时。
    backend = ROOT / "vista" / "backends" / "claude"
    files += [backend / n for n in ("factory.py", "runner.py", "provider.py",
                                    "lifecycle.py", "mcp_host.py", "mcp_bridge.py",
                                    "preflight.py")]
    return max((p.stat().st_mtime for p in files if p.exists()), default=0.0)


def start(name: str) -> subprocess.Popen:
    exe = sys.executable
    if name == "gui" and os.name == "nt":
        pyw = Path(exe).with_name("pythonw.exe")
        if pyw.exists(): exe = str(pyw)                    # 窗口进程不弹控制台
    DIR.mkdir(parents=True, exist_ok=True)
    out = (DIR / f"child_{name}.log").open("a", encoding="utf-8")
    return subprocess.Popen([exe, *CHILDREN[name]], cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),
                            creationflags=NO_WINDOW, stdout=out, stderr=subprocess.STDOUT)


# 单个子进程连续多少次启动失败就把它从**快速轮询**摘掉。start() 失败通常是
# 磁盘满/句柄耗尽，瞬时故障本该重试；但代码本身有语法错误时会永久失败，
# 每 2 秒重试一次只会刷满 CPU——超过这个次数就转入慢速探活（见下），其余部分
# 继续活着。30 次 × 2s = 60s 快速预算。
MAX_START_FAILS = 30
# 「活稳了」观察窗（秒）：Popen 成功不等于拉起成功。热更新写入带语法错误的
# brain 时，start() 正常返回、解释器启动后立刻非 0 退出；旧代码只对 start()
# 抛 OSError 计数，秒退 proc 下一 tick 走「退出已拉起、fails=0」，计数恒 0、
# 永不摘除（PR #16 复审 P1-1）。新 proc 存活不足此时长就退出 = 一次启动失败；
# 活过它才确认健康并清零。工程初值：监督 tick=2s，语法错误/缺依赖都在解释器
# 启动 1~2s 内暴露，给到 10s 留冷启动余量；无文献背书，实机观察后可调。
SPAWN_OBSERVE_S = 10.0
# 被摘孩子的慢速探活间隔（秒）。摘除不是永久死亡：真实 ENOSPC 事故持续约
# 3 分钟（17:06→17:09），旧代码 60s 预算耗尽后永久 pop，磁盘恢复 brain 也
# 不复活，精灵永久沉默（PR #16 复审 P1-2）。被摘孩子每这么久试拉一次，
# 活过 SPAWN_OBSERVE_S 即恢复正常轮询；探活失败静默等下一轮。
# 工程初值，无文献背书：最坏 1 分钟复活延迟可接受，磁盘满时也不会每 2s 刷失败。
RESPAWN_PROBE_S = 60.0


def spawn_children(names=CHILDREN, *, start=start, log=log, now=None) -> tuple:
    """启动期逐个拉起孩子；单个失败不许击穿整个监督进程。

    旧代码 ``{n: start(n) for n in CHILDREN}`` 在 try 之外（PR #16 复审 P2-4）：
    0 字节磁盘/句柄耗尽时第一个孩子 start() 抛 OSError，监督进程直接 traceback，
    一个孩子都没有。改成逐个容错：失败的孩子记一次失败并进慢速探活表
    （retry_at=0：第一轮 reconcile 立刻再试一次，之后按 RESPAWN_PROBE_S），
    其余孩子照常启动。返回 ``(procs, spawned, fails, dropped)`` 四态。
    """
    now = time.time() if now is None else float(now)
    procs: dict = {}
    spawned: dict = {}
    fails: dict = {}
    dropped: dict = {}
    for name in names:
        try:
            procs[name] = start(name)
        except OSError as exc:
            log(f"{name} 启动期拉起失败（{type(exc).__name__}），不影响其余孩子，"
                "进入慢速探活")
            fails[name] = 1
            dropped[name] = {"retry_at": 0.0, "proc": None, "spawned": None}
            continue
        spawned[name] = now
        fails[name] = 0
    return procs, spawned, fails, dropped


def reconcile_exits(procs: dict, fails: dict, *, start=start, log=log,
                    max_fails: int = MAX_START_FAILS, spawned: dict | None = None,
                    dropped: dict | None = None, now: float | None = None) -> dict:
    """检查并拉起已退出的子进程；连续启动失败达上限的孩子转慢速探活，且可复活。

    纯编排、可注入：``start``/``log``/``now`` 都是参数，测试不必真的拉起或杀掉
    任何进程、也不用真睡（issue #11 验收：监督容错此前零覆盖）。

    状态四件套（``spawned``/``dropped`` 缺省时内部临时建，产线由 supervise 持有）：

    - ``procs``   正常监督表里的孩子；
    - ``spawned`` name → 最近一次 spawn 时刻，用来区分秒退与正常退出；
    - ``fails``   name → 连续启动失败计数；
    - ``dropped`` name → 慢速探活状态 ``{"retry_at", "proc", "spawned"}``。

    计数规则（PR #16 复审 P1-1）：

    - 孩子活着且活过 ``SPAWN_OBSERVE_S``：确认健康，历史失败清零；
    - start 抛 OSError：计数 +1；
    - start 成功但新 proc 在 ``SPAWN_OBSERVE_S`` 内退出（热更新写入语法错误
      brain 的真实路径）：同样计数 +1，并再拉起一次；
    - 活过观察窗之后的退出（正常热更新/手动重启后的意外退出）：计 0、照常拉起；
    - 计数达 ``max_fails``：摘出快速轮询、转入慢速探活，其余孩子不受牵连。

    慢速探活（P1-2）：被摘孩子每 ``RESPAWN_PROBE_S`` 秒试拉一次；探活 proc
    活过观察窗才回到正常轮询并记恢复日志，探活失败静默等下一轮。brain/gui/
    recorder 三者行为完全一致。秒退达上限的那次 start 若已返回 proc，该 proc
    直接作为在飞探活 proc 被 dropped 接管（R2-1），而不是随 retire 的 pop 被
    遗弃成孤儿：故障恰在边界恢复时，它 10s 内就能被确认复活而无需再等 60s。
    其它（非 OSError）异常不在此吞——交给监督轮外层的 try/except，免得掩盖
    编程错误。``fails`` 原地更新并返回，``procs``/``spawned``/``dropped`` 原地改。
    """
    now = time.time() if now is None else float(now)
    if spawned is None:
        spawned = {}
    if dropped is None:
        dropped = {}

    def retire(name: str, reason: str, *, inflight=None) -> None:
        log(f"{name} 连续 {fails.get(name, 0)} 次{reason}，暂时放弃快速重试，"
            f"转入慢速探活（每 {RESPAWN_PROBE_S:.0f}s 试拉一次，"
            f"活过 {SPAWN_OBSERVE_S:.0f}s 才恢复），其余部分继续")
        procs.pop(name, None)
        spawned.pop(name, None)
        if inflight is None:
            dropped[name] = {"retry_at": now + RESPAWN_PROBE_S,
                             "proc": None, "spawned": None}
        else:
            # R2-1：本次秒退判定刚拉起的 proc 不许遗弃（先挂 procs 再 pop 会让它
            # 既不在 procs 也不在 dropped、从未 terminate，60s 后探活再拉即双开）。
            # 直接挂为在飞探活 proc：活过观察窗就由上面的探活逻辑确认复活，
            # 再次秒退则回等待继续探活——它始终处于「被跟踪或被 terminate」二态。
            dropped[name] = {"retry_at": now + RESPAWN_PROBE_S,
                             "proc": inflight, "spawned": now}

    # 1) 慢速探活：先于正常轮询处理，恢复成功的孩子本轮就交给下面的正常路径接管。
    for name in list(dropped):
        entry = dropped[name]
        probe = entry.get("proc")
        if probe is None:
            if now < float(entry["retry_at"]):
                continue
            try:
                probe = start(name)
            except OSError:
                # 探活失败静默等待下一轮：磁盘满时不刷日志、不刷 CPU。
                entry["retry_at"] = now + RESPAWN_PROBE_S
                continue
            entry["proc"] = probe
            entry["spawned"] = now
            continue
        age = now - float(entry["spawned"])
        if probe.poll() is None:
            if age >= SPAWN_OBSERVE_S:
                log(f"{name} 慢速探活成功（新进程已存活 {age:.0f}s），恢复正常监督轮询")
                procs[name] = probe
                spawned[name] = float(entry["spawned"])
                fails[name] = 0
                dropped.pop(name, None)
            continue
        if age < SPAWN_OBSERVE_S:
            # 探活 proc 秒退：回到等待，下一轮再试（不记日志，保持静默）。
            entry["proc"] = None
            entry["spawned"] = None
            entry["retry_at"] = now + RESPAWN_PROBE_S
            continue
        # 边界竞态：刚好活过观察窗才退出——按已恢复处理，本轮正常路径立刻接管。
        procs[name] = probe
        spawned[name] = float(entry["spawned"])
        fails[name] = 0
        dropped.pop(name, None)

    # 2) 正常监督表里的孩子。
    for name, proc in list(procs.items()):
        if proc.poll() is None:
            if name in spawned and now - spawned[name] >= SPAWN_OBSERVE_S and fails.get(name):
                fails[name] = 0
                log(f"{name} 已稳定存活超过 {SPAWN_OBSERVE_S:.0f}s，"
                    "连续启动失败计数清零")
            continue
        died_early = name in spawned and now - spawned[name] < SPAWN_OBSERVE_S
        try:
            new = start(name)
        except OSError as exc:
            fails[name] = fails.get(name, 0) + 1
            if fails[name] >= max_fails:
                retire(name, f"拉不起来（{type(exc).__name__}）")
            continue
        procs[name] = new
        spawned[name] = now
        if died_early:
            # Popen 成功但新进程秒退，与 start() 抛 OSError 同属一次启动失败：
            # 不能因为 start 没抛异常就把计数清零。
            fails[name] = fails.get(name, 0) + 1
            if fails[name] >= max_fails:
                # new 交给 retire 挂为在飞探活 proc，不能让它随 pop 变成孤儿。
                retire(name, "启动后秒退", inflight=new)
            else:
                log(f"{name} 启动后 {SPAWN_OBSERVE_S:.0f}s 内退出"
                    f"（连续第 {fails[name]} 次，疑似启动即崩），已再拉起")
        else:
            # 活过观察窗之后的退出计 0：热更新/手动重启后的意外退出，照常拉起。
            fails[name] = 0
            log(f"{name} 退出，已自动拉起")
    return fails


def supervise() -> None:
    procs, spawned, start_fails, dropped = spawn_children()
    seen_all, seen_brain = watched_stamp(), brain_stamp()
    log("启动：brain（持续视觉上下文）+ 窗口 + 操作记录器")

    def hot_swap(name: str) -> None:
        """代码变了：无条件换一个新 proc（编辑代码本身就是显式复活信号）。

        也要接管慢速探活中的孩子（P1-2）：它不在 procs 而在 dropped 里，
        探活 proc 在飞就先 terminate。start() 若抛 OSError，把它重设为
        retry_at=0 的探活（下一轮立刻试）后继续抛出交给外层 try——避免它
        既不在 procs 也没有探活计划，或之后探活路径双开第二个同名孩子。
        必须在成功后才更新 spawned，热重启的秒退才会被 P1-1 计数。
        """
        old = procs.pop(name, None)
        entry = dropped.pop(name, None)
        if old is None and entry is not None:
            old = entry.get("proc")
        if old is not None:
            old.terminate()
            try:
                old.wait(10)
            except subprocess.TimeoutExpired:
                old.kill()
        try:
            new = start(name)
        except OSError:
            dropped[name] = {"retry_at": 0.0, "proc": None, "spawned": None}
            raise
        procs[name] = new
        spawned[name] = time.time()

    try:
        while True:
            time.sleep(CHECK_S)
            # 整个循环体包住：这一轮的任何异常都不能杀死监督进程。
            # 10-13 的事故是 log() 的 ENOSPC 穿出去带走了全部子进程；同类
            # 风险还有 stat()、start()、poll()。它们都是可恢复的瞬时故障，
            # 而「监督进程活着」本身就是精灵不消失的前提。
            try:
                reconcile_exits(procs, start_fails, spawned=spawned, dropped=dropped)
                b = brain_stamp()
                if b != seen_brain:
                    # 只有 brain 自己变了才重启它：它正在积累的视觉上下文比新代码更值钱
                    seen_brain = b
                    log("brain 代码变了：重启 brain（视觉上下文会重来，这是必要代价）")
                    hot_swap("brain")
                a = watched_stamp()
                if a != seen_all:
                    # 别的文件变了：不杀 brain。改动会在它下一轮自然生效。
                    seen_all = a
                    hot_swap("gui")
                    log("其它代码变了：只热更新窗口，brain 的持续视觉上下文保留")
            except OSError as exc:
                # 磁盘满、句柄耗尽之类。丢掉这一轮的判断，下一轮再来。
                log(f"监督轮异常（{type(exc).__name__}），已跳过，精灵继续运行")
            except Exception as exc:
                log(f"监督轮未预期异常（{type(exc).__name__}: {exc}），已跳过，精灵继续运行")
    except KeyboardInterrupt:
        pass
    finally:
        for p in list(procs.values()):
            try: p.terminate()
            except Exception: pass
        # 慢速探活中在飞的 proc 也要收掉，否则监督退出后它会变成孤儿。
        for entry in dropped.values():
            p = entry.get("proc")
            if p is not None:
                try: p.terminate()
                except Exception: pass
        log("已停止")


def read_current() -> dict | None:
    try: return json.loads(CURRENT.read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def queue_message(text: str) -> str:
    current = read_current() or {}
    feedback = add_feedback(text, current.get("activity", ""))
    conversation.append("user", text, kind="message", event_id=f"message:{feedback['t']}", t=feedback["t"])
    # 用户主动打字回话 = 这一次开口被接住了，比任何“好”按钮都强
    record_outcome(CURRENT_OFFER.get("offer"), "responded", said=text[:200])
    return ""


def drop_dead_dialog(opened: dict) -> None:
    """Forget the current dialog, closing it first if it is still alive.

    ``opened["dlg"]`` is a live Tk reference, but the user can close the toplevel
    at any moment (click ×, press Esc) while the offer thread is still writing to
    the transcript. Touching that dead reference raises TclError, so every contact
    goes through here: clear the entry **first**, then try to close, so a raising
    ``close()`` can never leave a stale reference behind for the next tick.
    """
    dlg = opened.get("dlg")
    if dlg is None:
        return
    opened["dlg"] = None
    try:
        dlg.close()
    except Exception:
        # Already destroyed / Tk gone. The reference is already dropped, which is
        # the only thing the caller needed.
        pass


def run_gui() -> None:
    import tkinter as tk
    from ..gui import SpriteWindow, enable_dpi_awareness, W, H, SCALE
    from .dialog import ChatDialog
    enable_dpi_awareness(); root = tk.Tk(); root.withdraw()
    offer_state: dict = {"id": None, "offer": None, "running": None}
    opened = {"dlg": None}

    def present(msg: dict, seconds: float, *, event_id: str | None = None) -> None:
        """Show immediately and append to the conversation without blocking tick()."""
        text = str(msg.get("text") or "").strip()
        if text and text != IDLE_HINT_TEXT:
            conversation.append("assistant", text, kind=str(msg.get("kind") or "say"),
                                event_id=event_id, reply_to=msg.get("reply_to"))
        # A long lived chat window must never hide an action or completion
        # report. The transcript is persisted, so closing it here loses no
        # context and lets the user see the current work immediately.
        if (msg.get("kind") == "action"
                or str(event_id or "").endswith(":started")
                or str(event_id or "").endswith(":completed")):
            drop_dead_dialog(opened)
        w.show(msg, seconds)
        dlg = opened.get("dlg")
        if dlg is not None:
            try:
                dlg.set_history(conversation.history())
            except Exception:
                # The dialog may have been closed between the offer write and
                # this GUI tick. Drop the stale Tk reference; the next click
                # will create a fresh dialog.
                opened["dlg"] = None

    def present_say(msg: dict, *, floor: float = BUBBLE_READ_S,
                    event_id: str | None = None) -> None:
        """一句话气泡：停留时长由这句话本身的长度决定，不写死。"""
        present(msg, bubble_seconds(msg.get("text"), floor=floor), event_id=event_id)

    def on_choice(i, ok=False) -> None:
        """用户对 offer 点了某个选项。**只有点了第一个（好的）才执行。**

        旧版这里只记账、不启动执行——因为 tick 从来不等它，直接就 auto_started 了。
        现在执行权就在这个回调里：offer 不再自动动手，点头是唯一的开关。
        """
        offer = offer_state["offer"]
        if not offer:
            return
        if i is not None:
            options = offer.get("options") or []
            label = options[i] if 0 <= i < len(options) else None
            record_outcome(offer, "accepted" if i == 0 else "rejected",
                           options=options, choice_index=i, choice=label)
            # 先收起带选项的气泡，再开始执行：start_offer 会 present 一条新气泡，
            # 顺序反了会把「好，我开始处理…」一起收掉。
            w.hide(expired=False)
            if i == 0:
                start_offer(offer)
            return
        if ok:
            record_outcome(offer, "acknowledged")
        w.hide(expired=False)

    def start_offer(offer: dict) -> None:
        """用户点了「好的」：现在才真的开始执行。"""
        offer_state["running"] = offer.get("id")
        record_offer_result(offer, "started")
        label = offer.get("topic") or "这件事"
        present_say(dict(kind="say", text=f"好，我开始处理{label}，完成后告诉你。"),
                    event_id=f"{offer.get('id')}:started")

        def report(msg: dict) -> None:
            def deliver() -> None:
                # 完成汇报可能很长（批次结果、路径清单），给足读完的时间，
                # 但仍然有上限——它不该变成一块常驻在屏幕上的告示牌。
                present(msg, bubble_seconds(msg.get("text"), floor=45.0),
                        event_id=f"{offer.get('id')}:completed")
                # running 的解除与气泡时长无关：一次 run_offer 最多跑 900s，
                # 早于那时清掉会让 tick 把后续进度气泡当成新提议重新处理。
                root.after(WORKING_GUARD_MS, lambda: offer_state.update(running=None))
            root.after(0, deliver)

        if offer.get("items"):
            # 风险分级批次：执行提议里**逐条列出的**操作，不重新让模型决定一遍。
            # 批准的是这份清单 —— 若改成再跑一次任务，点头批准的范围就被悄悄放大了。
            threading.Thread(target=run_risk_batch, args=(offer, report), daemon=True).start()
            return
        threading.Thread(target=run_offer, args=(offer, report), daemon=True).start()

    def on_expire() -> None:
        """气泡自己超时消失、用户全程没反应 —— 最常发生、也最该被记下来的情况。

        对 offer 来说这就是「没点头」：**不执行**。同时把 expired 写进 offers.jsonl，
        否则窗口重启后 offer.json 还在、状态又还没落账，同一条提议会被重新弹一次
        （offer_status 只认已落盘的结果行）。
        记什么结果交给 expiry_outcome 判：真给过选项才算 ignored，没给选项只记 unanswered。
        """
        shown = offer_state.get("offer")
        record_outcome(shown, expiry_outcome(shown))
        # 只在「还没点头」时作废。用户已经点了好的、动作正在跑（offer_state["running"]），
        # 这时超时的是后续的进度气泡，不能给这条提议补一条 expired。
        if (shown and str(shown.get("kind") or "") == "offer"
                and not offer_state.get("running")
                and offer_status(shown.get("id")) not in SETTLED_OFFER_STATES):
            record_offer_result(shown, "expired")

    def on_undo(_aid) -> None:
        offer = offer_state.get("offer")
        if offer:
            record_offer_result(offer, "undo_requested")

        def undo_and_report() -> None:
            try:
                text = undo_offer()
            except Exception:
                text = "撤回没有启动成功，请稍后再试。"
            if offer:
                record_offer_result(offer, "undone")
            root.after(0, lambda: present_say(dict(kind="say", text=text)))

        threading.Thread(target=undo_and_report, daemon=True).start()

    w = SpriteWindow(root, DIR, on_choice, on_undo, on_expire)
    w.set_state("observing")
    # 待机提示。原来是 3600s——那句话会在屏幕上钉一小时，用户看到的就是
    # 「同一句话一直显示」；而且它是被过滤掉不写进对话记录的，等于屏幕上
    # 挂着一句幽灵话。点精灵随时能开对话框，这个提示只需要露个面。
    IDLE_HINT_S = 6.0
    w.show(dict(kind="say", text=IDLE_HINT_TEXT), IDLE_HINT_S)
    shown = {"t": None}

    def tick() -> None:
        try:
            offer = read_offer()
            if offer and offer.get("id") != offer_state["id"]:
                offer_state.update(id=offer.get("id"), offer=offer, running=None)
                CURRENT_OFFER.update(id=offer.get("id"), offer=offer)
                if offer.get("kind") == "companion":
                    # 闲聊气泡按长度计时。原来固定 180s：一句 20 字的话
                    # 在屏幕上钉三分钟，读完早就走了，看着像卡住不动。
                    present_say(dict(kind="say", text=offer["text"],
                                     reply_to=offer.get("reply_to")),
                                event_id=str(offer.get("id") or ""))
                elif offer_status(offer.get("id")) not in SETTLED_OFFER_STATES:
                    # 同意门：offer 到这里只是**把选项摆到用户面前**，不执行。
                    # gui._buttons 见到 options 就会画出「好的/不用」，点击走 on_choice，
                    # 只有选第一个才 start_offer。没人点 → on_expire → 到期作废。
                    options = list(offer.get("options") or OFFER_OPTIONS)
                    offer["options"] = options
                    present(dict(kind="offer", text=offer["text"], options=options,
                                 reply_to=offer.get("reply_to")),
                            OFFER_ASK_S, event_id=str(offer.get("id") or ""))
            row = read_current()
            if row and not offer_state.get("running"):
                # Keep current.json available to the feedback dialog, but do not
                # show status-only narration as a bubble.
                shown["t"] = row.get("t")
        except Exception as exc:
            # A malformed/stale offer must never silence the resident window.
            print(f"gui tick error: {type(exc).__name__}", flush=True)
        finally:
            root.after(2000, tick)

    def open_dialog() -> None:
        drop_dead_dialog(opened)
        current = read_current() or {}
        about = current.get("activity", "")
        state = current.get("state", "")
        next_step = current.get("next_step") or {}
        plan = ""
        if isinstance(next_step, dict):
            action = str(next_step.get("action") or "").strip()
            step_status = str(next_step.get("status") or "").strip()
            if action and step_status in {"ready", "waiting"}:
                plan = f"\n下一步：{action}"
        status = f"我判断你现在在：{about}\n{state}{plan}" if about else "我还在看，还没有判断。"
        sx, sy = w.sx, w.sy
        opened["dlg"] = ChatDialog(root, sx, sy, status, queue_message, conversation.history())

    press = {}

    def on_press(e) -> None:
        press["xy"] = (e.x_root, e.y_root)

    def on_release(e) -> None:
        x0, y0 = press.get("xy", (e.x_root, e.y_root))
        on_sprite = w.ox <= e.x <= w.ox + W * SCALE and w.oy <= e.y <= w.oy + H * SCALE
        if on_sprite and abs(e.x_root - x0) + abs(e.y_root - y0) <= 4: open_dialog()

    w.c.bind("<ButtonPress-1>", on_press, add="+")
    w.c.bind("<ButtonRelease-1>", on_release, add="+")
    root.after(300, tick); root.mainloop()


def read_offer() -> dict | None:
    try:
        offer = json.loads((DIR / "offer.json").read_text(encoding="utf-8"))
        # companion 是信息性的一句话：重启宽限只给到「它本来还该在屏幕上活的
        # 时间 + 一次重启」（见 companion_max_age_s），旧值 900s 会让 15 分钟前
        # 的闲聊在每次热更新后复活重弹。action offer 仍保持短命，过期动作绝不执行。
        max_age = (companion_max_age_s(offer) if offer.get("kind") == "companion"
                   else OFFER_MAX_AGE_S)
        if time.time() - float(offer.get("t", 0)) > max_age:
            return None
        return offer
    except (OSError, ValueError): return None


OUTCOMES = DIR / "outcomes.jsonl"
CURRENT_OFFER: dict = {"id": None, "offer": None}
_RECORDED: set = set()
_RECORDED_STAMP: tuple = ()


def _load_recorded() -> None:
    """把已落盘的 id 读进来。

    进程重启（supervisor 热更新）后 _RECORDED 会清空；只靠内存去重，
    同一条 offer 会被重复记一行（10-12 10:12 实测：同 id 记了 2 行）。
    """
    global _RECORDED_STAMP
    try:
        st = OUTCOMES.stat()
    except OSError:
        return
    stamp = (st.st_mtime_ns, st.st_size)
    if stamp == _RECORDED_STAMP:
        return
    try:
        with OUTCOMES.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("id"):
                    _RECORDED.add(row["id"])
    except OSError:
        return
    _RECORDED_STAMP = stamp


def expiry_outcome(shown: dict | None) -> str:
    """气泡超时消失该记哪种结果：**沉默不是回答**。

    只有真把选项摆到用户面前、他看见了却没选，才算一次明确的“不要”（ignored）。
    没给选项的气泡（companion / say，以及没带 options 的 offer）超时，用户根本没得选，
    那只是“没证据”（unanswered）——不能记成负例：他没在看屏幕，跟这句话有没有用无关。

    旧代码对所有超时一律记 ignored，而 timing.py 又把 ignored 当负例，于是每 3 分钟
    一句 companion 没人理就攒一个“负样本”，“越没人理越爱开口”（见 timing.learned_benefit_s）。
    """
    if not isinstance(shown, dict):
        return "unanswered"
    if str(shown.get("kind") or "") != "offer":
        return "unanswered"
    options = shown.get("options") or []
    return "ignored" if options else "unanswered"


def record_outcome(offer: dict | None, outcome: str, **extra) -> None:
    """写这次开口的最终结果 r_t —— 主动感知唯一的学习信号。

    outcome ∈ {accepted, rejected, acknowledged, responded, ignored, unanswered}：
      accepted     用户在选项里选了第一个（表示愿意）
      rejected     用户选了非第一个选项
      acknowledged 用户点了「好」把气泡关掉（只表示看见，不等于愿意）
      responded    用户直接在对话框里打字回话
      ignored      带选项的气泡超时消失：选项摆出来了、他看见了却没选，是一次明确的“不要”
      unanswered   没给选项的气泡（companion / say）超时消失：沉默不是回答，不当作负样本
    一行一次，join key 是 offer['id']；独立账本，不改动 offers.jsonl 的既有读者。
    """
    offer = offer or {}
    offer_id = offer.get("id")
    if not offer_id:
        return
    _load_recorded()
    if offer_id in _RECORDED:
        return
    _RECORDED.add(offer_id)
    now = time.time()
    try:
        latency = round(now - float(offer.get("t") or now), 3)
    except (TypeError, ValueError):
        latency = None
    row = {
        "id": offer_id,
        "t": now,
        "outcome": outcome,
        "latency_s": latency,
        "kind": offer.get("kind"),
        "topic": offer.get("topic"),
        "text": (offer.get("text") or "")[:200],
        **extra,
    }
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        with OUTCOMES.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def record_offer_result(offer: dict, result: str, **extra) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with (DIR / "offers.jsonl").open("a", encoding="utf-8") as f:
        row = dict(offer, result=result, t_answer=time.time(), **extra)
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def offer_status(offer_id: str | None) -> str | None:
    """Return the latest execution state so a GUI restart cannot run an offer twice."""
    if not offer_id:
        return None
    path = DIR / "offers.jsonl"
    if not path.exists():
        return None
    state = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("id") == offer_id:
            state = row.get("result")
    return state


def main(argv=None) -> None:
    if "--gui" in (argv or sys.argv[1:]): run_gui()
    else: supervise()


if __name__ == "__main__":
    main()
