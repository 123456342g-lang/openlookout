"""主动触发器：只读系统状态（不调模型、不花 token）；发现问题才唤醒 opencode 去自己调查、自己处理。
两类情况：
- mem：可用内存持续低于阈值 → agent 找占内存的东西，挂起/结束明显无用的进程。
- disk：C 盘剩余空间持续低于阈值 → agent 找能安全移走的大文件，移到 E 盘隔离区（隔离区不能在 C 盘上，否则不释放空间）。
所有会改变系统的操作先写 undo.jsonl；气泡上的“撤销”按日志倒序还原。
是否解决只看前后实测（内存/剩余空间），不信 agent 自述。
python -m sprite.proactive.trigger [--mem-threshold 0.20] [--disk-threshold 0.10] [--model opencode/xxx] [--no-gui] [--dry]"""
from __future__ import annotations
import argparse, json, os, queue, re, shutil, subprocess, threading, time
from dataclasses import dataclass
from pathlib import Path
import psutil

from ..config import sprite_home

WS = Path(__file__).resolve().parent / "ws"
HOME = sprite_home()
UNDO_LOG = HOME / "undo.jsonl"
QUARANTINE = HOME / "quarantine"
SYSTEM_DRIVE = "C:\\"
POLL_S, SUSTAIN, COOLDOWN_S, AGENT_TIMEOUT_S, SETTLE_S, ATTEMPTS = 5, 2, 600, 300, 20, 2
DETACHED = 0x00000008 if os.name == "nt" else 0


@dataclass
class Situation:
    kind: str          # mem | disk
    frac: float        # 当前剩余比例
    gb: float          # 当前剩余 GB
    threshold: float


def measure(kind: str) -> tuple[float, float]:
    if kind == "mem":
        m = psutil.virtual_memory(); return m.available / m.total, m.available / 2**30
    u = psutil.disk_usage(SYSTEM_DRIVE); return u.free / u.total, u.free / 2**30


def settle(kind: str, threshold: float) -> tuple[float, float]:
    """处理完后回收有延迟：最多等 SETTLE_S 秒，回到阈值以上就提前结束。"""
    end = time.time() + SETTLE_S
    while True:
        frac, gb = measure(kind)
        if frac >= threshold or time.time() >= end: return frac, gb
        time.sleep(2)


# 只给目标、边界和输出格式；查什么、怎么判断、用什么办法都由 agent 自己决定。
UNDO_RULE = (f"每一个改变这台电脑的操作，在执行前先往 {UNDO_LOG} 追加一行 JSON，"
             '格式 {"desc":"一句话说明","undo_cmd":"能把它完整还原的命令","cwd":"工作目录"}。没有还原方法的操作不做。')
BOUNDARY = "不删除任何东西，所有改动都必须能还原。"
RESULT_RULE = ("做完重新测量，然后最终回复只能是一个 JSON 对象，不要别的文字：\n"
               '{"cause":"原因，一句大白话，面向完全不懂电脑的人，不要出现进程号、PID、MB、命令等术语",'
               '"did":"你替用户做了什么，一句大白话；没做就留空",'
               '"offer":null 或 {"label":"建议用户处理的东西，大白话","why":"好处，一句话","cmd":"执行命令","undo_cmd":"还原命令","cwd":""},'
               '"detail":"给技术人员看的细节，可以写技术内容"}。'
               "offer 用于：你判断它是主要原因，但你不该替用户做决定（比如可能是用户在用的东西）。")

MEM_GOAL = "目标：让这台电脑恢复流畅。"
DISK_GOAL = f"目标：让 C 盘恢复足够的剩余空间。可用于放置改动的存放位置：{QUARANTINE}（这个目录在 E 盘）。"


def build_prompt(s: Situation) -> str:
    if s.kind == "mem":
        head = f"[系统自动触发，用户没有提问] 这台 Windows 电脑内存告急：可用 {s.gb:.1f}GB（{s.frac:.0%}），用户正感到卡顿。"
        return f"{head}{MEM_GOAL}{BOUNDARY}{UNDO_RULE}\n{RESULT_RULE}"
    head = f"[系统自动触发，用户没有提问] Windows 的 C 盘快满了：剩余 {s.gb:.1f}GB（{s.frac:.0%}），保存文件、更新时可能失败。"
    return f"{head}{DISK_GOAL}{BOUNDARY}{UNDO_RULE}\n{RESULT_RULE}"


def _parse_events(stdout: str) -> tuple[str, str]:
    """返回 (最后一段文字, 错误信息)。"""
    texts, err = [], ""
    for line in stdout.splitlines():
        try: d = json.loads(line)
        except ValueError: continue
        if d.get("type") == "text": texts.append(d.get("part", {}).get("text", ""))
        elif d.get("type") == "error": err = str(d.get("error", {}).get("data", {}).get("message") or d.get("error"))
    return (texts[-1] if texts else ""), err


def _extract_json(text: str) -> dict | None:
    for m in reversed(list(re.finditer(r"\{.*\}", text, re.S))):
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict): return d
        except ValueError: continue
    return None


def run_agent(prompt: str, model: str | None) -> dict:
    """成功返回 agent 的结论 dict；失败返回 {"_failed": 原因}。出错/超时/说不成 JSON 都重试。"""
    exe = shutil.which("opencode") or "opencode"
    cmd = [exe, "run", "--format", "json", "--dir", str(WS)] + (["-m", model] if model else []) + [prompt]
    why = ""
    for _ in range(ATTEMPTS):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=AGENT_TIMEOUT_S, cwd=WS)
        except subprocess.TimeoutExpired:
            why = "分析超时"; continue
        text, err = _parse_events(r.stdout)
        d = _extract_json(text)
        if d is not None and not err: return d
        why = err or "没有得到有效结论"
    return {"_failed": why}


def _undo_rows() -> list:
    rows = []
    if UNDO_LOG.exists():
        for line in UNDO_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try: rows.append(json.loads(line))
            except ValueError: pass
    return rows


def _run_cmd(cmd: str, cwd: str | None) -> None:
    subprocess.Popen(cmd, shell=True, cwd=cwd or None, creationflags=DETACHED,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def undo_all() -> int:
    n = 0
    for r in reversed(_undo_rows()):
        try: _run_cmd(r["undo_cmd"], r.get("cwd")); n += 1
        except Exception as e: print("撤销失败：", r.get("desc"), e, flush=True)
    if UNDO_LOG.exists(): UNDO_LOG.rename(UNDO_LOG.with_suffix(f".{int(time.time())}.done"))
    return n


def compose(kind: str, d: dict, gb0: float, frac1: float, gb1: float, threshold: float, acted: bool) -> dict:
    """把实测结果和 agent 结论合成给普通用户看的气泡。返回 {state, text, detail, offer, undo}。"""
    ok = frac1 >= threshold
    unit, what = ("可用内存", "电脑卡") if kind == "mem" else ("C 盘剩余", "C 盘快满了")
    cause, offer = (d.get("cause") or "").strip(), d.get("offer")
    did = (d.get("did") or "").strip().rstrip("。.！! ")
    detail = f"{unit} {gb0:.1f}→{gb1:.1f}GB\n" + (d.get("detail") or d.get("_failed") or "")
    out = lambda text, offer=None, undo=acted: dict(state="idle", text=text, detail=detail, offer=offer, undo=undo)
    if d.get("_failed"):
        return out((f"{what}，但我这次没能查清原因。" + ("已做的操作可以撤销。" if acted else "没有动你的任何东西。")) if not ok else "已经恢复正常了。")
    if ok:
        return out(f"搞定了，{what.replace('快满了', '腾出来了').replace('卡', '不卡了')}。" + (did + "。" if did else (cause + "。" if cause else "")))
    if isinstance(offer, dict) and offer.get("cmd") and offer.get("undo_cmd") and offer.get("label"):
        offer = dict(offer, kind=kind)
        return out((did + "，但还是不够。" if did else f"{what}。") + f"主要是{offer['label']}。{offer.get('why', '')}要我处理吗？（可以恢复）", offer=offer, undo=False)
    return out((did + "，但还是不够。" if did else "我没找到可以放心处理的东西。") + ("电脑内存本身不太够用，少开几个程序会好很多。" if kind == "mem" else "C 盘里大部分是系统和程序本身，可以考虑卸载不用的软件。"))


def handle(s: Situation, model: str | None, say) -> None:
    HOME.mkdir(parents=True, exist_ok=True); QUARANTINE.mkdir(parents=True, exist_ok=True)
    UNDO_LOG.write_text("", encoding="utf-8")
    say(dict(state="thinking", text="C 盘好像快满了，我去看看……" if s.kind == "disk" else "电脑好像卡了，我去看看……"))
    d = run_agent(build_prompt(s), model)
    frac1, gb1 = settle(s.kind, s.threshold)
    say(compose(s.kind, d, s.gb, frac1, gb1, s.threshold, acted=bool(_undo_rows())))


def accept_offer(offer: dict, kind: str, threshold: float, say) -> None:
    """用户点了“处理”：先记还原命令，再执行，再按实测汇报。"""
    _, gb0 = measure(kind)
    with UNDO_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(desc=f"处理{offer['label']}", undo_cmd=offer["undo_cmd"], cwd=offer.get("cwd") or ""), ensure_ascii=False) + "\n")
    _run_cmd(offer["cmd"], offer.get("cwd"))
    frac1, gb1 = settle(kind, threshold)
    ok = frac1 >= threshold
    say(dict(state="idle", text="好了。" if ok else "处理了，但还是不够。", detail=f"{gb0:.1f}→{gb1:.1f}GB", offer=None, undo=True))


def monitor(thresholds: dict, model: str | None, say, stop: threading.Event, dry: bool) -> None:
    low = {k: 0 for k in thresholds}; last = {k: 0.0 for k in thresholds}
    while not stop.is_set():
        for kind, threshold in thresholds.items():
            frac, gb = measure(kind)
            low[kind] = low[kind] + 1 if frac < threshold else 0
            if low[kind] >= SUSTAIN and time.time() - last[kind] > COOLDOWN_S:
                last[kind] = time.time(); s = Situation(kind, frac, gb, threshold)
                if dry: print("[dry] 触发：", build_prompt(s), flush=True)
                else: handle(s, model, say)
        stop.wait(POLL_S)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mem-threshold", type=float, default=0.20); ap.add_argument("--disk-threshold", type=float, default=0.10)
    ap.add_argument("--model"); ap.add_argument("--no-gui", action="store_true"); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv); stop = threading.Event(); q: queue.Queue = queue.Queue(); pending: dict = {}
    thresholds = {"mem": a.mem_threshold, "disk": a.disk_threshold}

    def say(m: dict):
        print(f"[{m['state']}] {m['text']}" + (f"\n  详情：{m['detail']}" if m.get("detail") else ""), flush=True)
        pending["offer"] = m.get("offer"); q.put(m)

    threading.Thread(target=monitor, args=(thresholds, a.model, say, stop, a.dry), daemon=True).start()
    if a.no_gui:
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: stop.set(); return
    import tkinter as tk
    from ..gui import SpriteWindow, enable_dpi_awareness
    enable_dpi_awareness(); root = tk.Tk(); root.withdraw()

    def on_choice(i, ok=False):
        offer, pending["offer"] = pending.get("offer"), None
        if offer and i == 0 and not ok:
            threading.Thread(target=accept_offer, args=(offer, offer["kind"], a.disk_threshold if offer["kind"] == "disk" else a.mem_threshold, say), daemon=True).start()

    def on_undo(_aid):
        q.put(dict(state="idle", text=f"已经还原了 {undo_all()} 项操作。", detail=None, offer=None, undo=False))

    w = SpriteWindow(root, WS, on_choice, on_undo, lambda: None)

    def pump():
        try:
            while True:
                m = q.get_nowait(); w.set_state(m["state"])
                msg = dict(kind="say", text=m["text"], detail=m.get("detail"))
                if m.get("offer"): msg["options"] = ["处理它", "先不用"]
                elif m.get("undo"): msg.update(kind="action", action_id="u")
                w.show(msg, 60)
        except queue.Empty: pass
        root.after(500, pump)

    root.after(200, pump); root.mainloop(); stop.set()


if __name__ == "__main__":
    main()
