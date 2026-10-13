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
from . import conversation

ROOT = Path(__file__).resolve().parents[2]                       # src/openlookout
OFFER_GOAL = ("小精灵已经决定主动替用户处理这件事：「{text}」。请你现在就自己判断怎么帮他做，用合适的办法。"
              "原则：不绕过安全检查，不删除文件，不结束用户正在用的程序；每个会改变电脑的操作，先记录撤回方法。"
              "只做安全、可撤回的动作；不等待用户确认。做完用一句温和的话报告做了什么。")


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
CHECK_S, SHOW_S = 2, 3600
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
OFFER_MAX_AGE_S = 180
CURRENT_MAX_AGE_S = 15


def log(msg: str) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%H:%M:%S} {msg}"
    with SUP_LOG.open("a", encoding="utf-8") as f: f.write(line + "\n")
    print(line, flush=True)


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


def supervise() -> None:
    procs = {n: start(n) for n in CHILDREN}
    seen_all, seen_brain = watched_stamp(), brain_stamp()
    log("启动：brain（持续视觉上下文）+ 窗口 + 操作记录器")
    try:
        while True:
            time.sleep(CHECK_S)
            for n, p in list(procs.items()):
                if p.poll() is not None:
                    procs[n] = start(n); log(f"{n} 退出，已自动拉起")
            b = brain_stamp()
            if b != seen_brain:
                # 只有 brain 自己变了才重启它：它正在积累的视觉上下文比新代码更值钱
                seen_brain = b
                log("brain 代码变了：重启 brain（视觉上下文会重来，这是必要代价）")
                p = procs.get("brain")
                if p: p.terminate()
                if p:
                    try: p.wait(10)
                    except subprocess.TimeoutExpired: p.kill()
                procs["brain"] = start("brain")
            a = watched_stamp()
            if a != seen_all:
                # 别的文件变了：不杀 brain。改动会在它下一轮自然生效。
                seen_all = a
                g = procs.get("gui")
                if g: g.terminate()
                if g:
                    try: g.wait(10)
                    except subprocess.TimeoutExpired: g.kill()
                procs["gui"] = start("gui")
                log("其它代码变了：只热更新窗口，brain 的持续视觉上下文保留")
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs.values(): p.terminate()
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

    def present(msg: dict, seconds: int, *, event_id: str | None = None) -> None:
        """Show immediately and append to the conversation without blocking tick()."""
        text = str(msg.get("text") or "").strip()
        if text and text != "我在准备下一步，点我可以直接聊天。":
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

    def on_choice(i, ok=False) -> None:
        """记录用户的选择再关气泡。动作是否已自动启动与这里无关。"""
        offer = offer_state["offer"]
        if not offer:
            return
        if i is not None:
            options = offer.get("options") or []
            label = options[i] if 0 <= i < len(options) else None
            record_outcome(offer, "accepted" if i == 0 else "rejected",
                           options=options, choice_index=i, choice=label)
        elif ok:
            record_outcome(offer, "acknowledged")
        w.hide(expired=False)

    def on_expire() -> None:
        """气泡自己超时消失、用户全程没反应 —— 最常发生、也最该被记下来的情况。

        记什么交给 expiry_outcome 判：真给过选项才算 ignored，没给选项只记 unanswered。
        """
        shown = offer_state.get("offer")
        record_outcome(shown, expiry_outcome(shown))

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
            root.after(0, lambda: present(dict(kind="say", text=text), 30))

        threading.Thread(target=undo_and_report, daemon=True).start()

    w = SpriteWindow(root, DIR, on_choice, on_undo, on_expire)
    w.set_state("observing")
    # Keep the conversation entry point discoverable even when the brain
    # correctly chooses quiet for the current screen. A real offer/report
    # replaces this bubble; otherwise it remains the idle affordance.
    w.show(dict(kind="say", text="我在准备下一步，点我可以直接聊天。"), 3600)
    shown = {"t": None}

    def tick() -> None:
        try:
            offer = read_offer()
            if offer and offer.get("id") != offer_state["id"]:
                offer_state.update(id=offer.get("id"), offer=offer, running=None)
                CURRENT_OFFER.update(id=offer.get("id"), offer=offer)
                if offer.get("kind") == "companion":
                    present(dict(kind="say", text=offer["text"], reply_to=offer.get("reply_to")),
                            180, event_id=str(offer.get("id") or ""))
                else:
                    status = offer_status(offer.get("id"))
                    if status not in {
                        "auto_started", "auto_completed", "auto_failed", "auto_no_answer",
                        "auto_errored", "accepted", "undone", "undo_requested", "ignored",
                        "acknowledged", "responded", "rejected",
                    }:
                        record_offer_result(offer, "auto_started")
                        offer_state["running"] = offer.get("id")
                        label = offer.get("topic") or "这件事"
                        present(dict(kind="say", text=f"我已经开始处理{label}，完成后告诉你。"), 120,
                                event_id=f"{offer.get('id')}:started")
                        def report(msg: dict) -> None:
                            def deliver() -> None:
                                present(msg, 120, event_id=f"{offer.get('id')}:completed")
                                root.after(120000, lambda: offer_state.update(running=None))
                            root.after(0, deliver)
                        threading.Thread(target=run_offer, args=(offer, report), daemon=True).start()
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
        # A companion sentence is informational and can wait through a GUI
        # restart; an action offer stays short-lived so stale actions never run.
        max_age = 900 if offer.get("kind") == "companion" else OFFER_MAX_AGE_S
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
