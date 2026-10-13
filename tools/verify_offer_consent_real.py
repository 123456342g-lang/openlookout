"""真机验证：offer 同意门在**真实 Tk 事件链路上**是否成立。

与单元测试的关键区别（也是这次任务的意义）：
  * 单元测试直接调`win._click(("choice", 0))`——那是「我调了回调」。
  * 这里用 `canvas.event_generate("<Button-1>", x=..., y=...)` 在**按钮实际被画出来的
    像素坐标上**投递一个真正的鼠标事件，走 Tk 自己的事件派发 →
    tag_bind → _click → on_choice → record_outcome → start_offer。
    也就是说：进程里没有人「主动调用」on_choice，是 UI 事件自己触发的。
  * 到期作废那一路连 `hide(expired=True)` 都不调：把 OFFER_ASK_S 调小，让 gui.show
    自己排的 `after` 定时器**真的到期**，on_expire 由定时器触发。

安全边界（必须说清楚）：
  同意门的位置在 run_offer **之前**。所以「点头之前一个动作都不许发生」这件事，
  可以被真机验证；但「点头之后 VISTA/Claude 真的去动电脑」是另一条链路，
  本脚本**故意不打通**——它会把 live.subprocess.run 换掉，让 run_offer 走完流程、
  落真实的 auto_completed 账，但对系统零改动（不删文件、不碰进程、不动 C 盘）。
  真实桌面任务从未在无同意的情况下被验证过，也不该由这个脚本去验证。

隔离：SPRITE_HOME 在import perceive **之前** 换掉，之后再断言 perceive.DIR 真的落在
临时目录里（不假设，只验证）。真实账本 E:\\OpenLookout\\sprite_home 一行都不碰。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="ol_gate_real_")).resolve()
os.environ["SPRITE_HOME"] = str(HOME)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "openlookout"))

# ── 先证明 SPRITE_HOME 真的生效（不假设） ──────────────────────────────────
from sprite.proactive import perceive  # noqa: E402

_dir = Path(perceive.DIR).resolve()
ISOLATED = str(_dir).startswith(str(HOME))
print(f"[isolation] SPRITE_HOME   = {HOME}")
print(f"[isolation] perceive.DIR  = {_dir}")
print(f"[isolation] real ledger   = {perceive.HOME and 'E:/OpenLookout/sprite_home'}")
print(f"[isolation] ISOLATED={ISOLATED}")
assert ISOLATED, "SPRITE_HOME 没生效，拒绝继续（会写进真实账本）"

import tkinter as tk  # noqa: E402

from sprite.gui import SpriteWindow  # noqa: E402
from sprite.proactive import conversation, help as helpmod, live  # noqa: E402

DIR = HOME / "perceive"
DIR.mkdir(parents=True, exist_ok=True)
live.DIR, live.OUTCOMES = DIR, DIR / "outcomes.jsonl"
live.CURRENT, live.SUP_LOG = DIR / "current.json", DIR / "supervisor.log"
helpmod.DIR, helpmod.OFFER = DIR, DIR / "offer.json"
helpmod.OFFER_LOG, helpmod.ACT_JSONL = DIR / "offers.jsonl", DIR / "activity.jsonl"
conversation.DIR, conversation.LOG = DIR, DIR / "conversation.jsonl"

# ── 绝不允许真的动电脑 ──────────────────────────────────────────────────────
EXECUTED: list[dict] = []


class _FakeProc:
    returncode = 0
    stdout = json.dumps({"answered": True, "final": "[验证脚本] 这一步是打桩的，电脑没被改动。"})
    stderr = ""


def _fake_run(argv, **kwargs):
    EXECUTED.append({"argv": list(argv)})
    return _FakeProc()


live.subprocess.run = _fake_run          # run_offer 内部用的就是 live.subprocess.run

_seq = {"n": 0}


def publish_offer(**over):
    _seq["n"] += 1
    offer = dict(id=f"real-{_seq['n']}", t=time.time(),
                 text="C盘快满了，要我清一下吗？", topic="C盘", kind="offer",
                 confidence=0.9, options=list(helpmod.OFFER_OPTIONS))
    offer.update(over)
    helpmod.publish(offer)                        # 走真实的 publish（原子写 offer.json）
    helpmod.record(dict(offer, result="shown"))   # 走真实的 record
    return offer


def rows(name):
    p = DIR / name
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]


def dump(title):
    print(f"\n───── {title} ─────")
    print("offers.jsonl :")
    for r in rows("offers.jsonl"):
        print("   ", json.dumps({k: r.get(k) for k in
              ("id", "kind", "topic", "result", "options", "choice", "choice_index", "report")
              if k in r}, ensure_ascii=False))
    print("outcomes.jsonl :")
    for r in rows("outcomes.jsonl"):
        print("   ", json.dumps(r, ensure_ascii=False))


def find_button(win, label):
    """找到画着这个文字的按钮，返回它在画布上的中心坐标。"""
    c = win.c
    for item in c.find_all():
        if c.type(item) == "text" and c.itemcget(item, "text") == label:
            x0, y0, x1, y1 = c.bbox(item)
            return (x0 + x1) // 2, (y0 + y1) // 2
    return None


def drive(script, ask_s=600):
    """跑一次真的 run_gui（真Tk、真 tick、真 w.show），只是把 mainloop 换成脚本。"""
    cap = {}
    real_init = SpriteWindow.__init__

    def spy_init(self, *a, **k):
        real_init(self, *a, **k)
        self.win.withdraw()          # 别在用户屏幕上弹窗；画布布局照常计算
        cap["win"] = self
    SpriteWindow.__init__ = spy_init
    live.OFFER_ASK_S = ask_s

    def pump(root, n=10):
        for _ in range(n):
            try:
                root.update()
            except tk.TclError:
                return
            time.sleep(0.02)

    def fake_mainloop(self, *a, **k):
        try:
            pump(self, 40)                    # 泵过 tick 的 root.after(300)
            script(cap["win"], lambda n=20: pump(self, n))
        finally:
            try:
                self.destroy()
            except tk.TclError:
                pass
        raise SystemExit(0)

    tk.Tk.mainloop = fake_mainloop
    try:
        live.run_gui()
    except SystemExit:
        pass
    finally:
        SpriteWindow.__init__ = real_init
    return cap["win"]


def reset():
    for p in DIR.glob("*"):
        if p.is_file():
            p.unlink()
    live._RECORDED.clear()
    live._RECORDED_STAMP = ()


# ══ 场景 A：真·鼠标事件点在「好的」上 ════════════════════════════════════════
print("\n" + "=" * 72)
print("场景 A：真 event_generate 点「好的」")
print("=" * 72)
reset()
offer_a = publish_offer()
info = {}


def script_a(win, pump):
    info["buttons"] = win._buttons()
    info["kind"] = win.msg.get("kind")
    info["has_options"] = "options" in win.msg
    pos = find_button(win, "好的")
    info["pos"] = pos
    print(f"[A] 气泡 kind={info['kind']} 带options={info['has_options']}")
    print(f"[A] 按钮 = {info['buttons']}")
    print(f"[A] 在画布坐标 {pos} 投递真实 <Button-1> 事件")
    win.c.event_generate("<Button-1>", x=pos[0], y=pos[1])
    pump(25)


drive(script_a)
dump("A:点了「好的」之后真实落盘的内容")
res_a = [r["result"] for r in rows("offers.jsonl")]
out_a = rows("outcomes.jsonl")
A_OK = (out_a and out_a[0]["outcome"] == "accepted"
        and out_a[0].get("choice") == "好的"
        and "started" in res_a
        and len(EXECUTED) == 1)
print(f"\n[A] outcomes outcome = {out_a[0]['outcome'] if out_a else None}")
print(f"[A] offers.jsonl results = {res_a}")
print(f"[A] run_offer 被调用次数 = {len(EXECUTED)}（argv 指向 vista cli = "
      f"{'vista.benchmarks.desktop.cli' in EXECUTED[0]['argv'] if EXECUTED else False}）")
print(f"[A] 结论: {'PASS' if A_OK else 'FAIL'}")

# ══ 场景 B：不点，让真定时器到期 ═════════════════════════════════════════════
print("\n" + "=" * 72)
print("场景 B：完全不点，让 gui.show 自己的 after 定时器真到期（OFFER_ASK_S=1）")
print("=" * 72)
reset()
EXECUTED.clear()
publish_offer(text="这条没人会点，等它自己过期")
n_before = len(EXECUTED)


def script_b(win, pump):
    print(f"[B] 气泡按钮 = {win._buttons()}")
    print("[B] 现在什么都不做，只泵事件循环等定时器自己到期 ...")
    pump(400)          # OFFER_ASK_S=1 -> gui.show 排 1*5=5s 的 after


drive(script_b, ask_s=1)
dump("B:没人点，到期之后真实落盘的内容")
res_b = [r["result"] for r in rows("offers.jsonl")]
out_b = rows("outcomes.jsonl")
B_OK = ("expired" in res_b and "started" not in res_b
        and len(EXECUTED) == n_before
        and out_b and out_b[0]["outcome"] in {"ignored", "unanswered"})
print(f"\n[B] offers.jsonl results = {res_b}")
print(f"[B] outcome = {out_b[0]['outcome'] if out_b else None}")
print(f"[B] 期间执行动作次数 = {len(EXECUTED) - n_before}")
print(f"[B] 结论: {'PASS' if B_OK else 'FAIL'}")

# ══ 场景 C：真事件点在「不用」上 ═════════════════════════════════════════════
print("\n" + "=" * 72)
print("场景 C：真 event_generate 点「不用」")
print("=" * 72)
reset()
EXECUTED.clear()
n_before = len(EXECUTED)
publish_offer(text="这个别做了")
info_c = {}


def script_c(win, pump):
    pos = find_button(win, "不用")
    info_c["pos"] = pos
    print(f"[C] 在画布坐标 {pos} 投递真实 <Button-1> 到「不用」")
    win.c.event_generate("<Button-1>", x=pos[0], y=pos[1])
    pump(20)


drive(script_c)
res_c = [r["result"] for r in rows("offers.jsonl")]
out_c = rows("outcomes.jsonl")
C_OK = (out_c and out_c[0]["outcome"] == "rejected"
        and "started" not in res_c and len(EXECUTED) == n_before)
print(f"\n[C] outcome = {out_c[0]['outcome'] if out_c else None}, choice={out_c[0].get('choice') if out_c else None}")
print(f"[C] offers.jsonl results = {res_c}")
print(f"[C] 执行次数 = {len(EXECUTED) - n_before}")
print(f"[C] 结论: {'PASS' if C_OK else 'FAIL'}")

print("\n" + "=" * 72)
print(f"隔离目录: {DIR}")
print(f"总结果: A(点头执行)={A_OK}  B(不点->过期不执行)={B_OK}  C(拒绝->不执行)={C_OK}")
print(f"真实账本被写入次数: 0（全部写入 {DIR}）")
print("=" * 72)

# ══ 场景 D：拒绝之后窗口重启，同一条提议不该再问 ════════════════════════════
print("\n" + "=" * 72)
print("场景 D：点「不用」→ 模拟窗口重启 → 断言不再被问（修复后的行为）")
print("=" * 72)
reset()
EXECUTED.clear()
offer_d = publish_offer(text="这条我已经拒绝过，别再问了")
d_info = {}


def script_d1(win, pump):
    pos = find_button(win, "不用")
    print(f"[D1] 真事件点「不用」于 {pos}")
    win.c.event_generate("<Button-1>", x=pos[0], y=pos[1])
    pump(20)


drive(script_d1)
res_d1 = [r["result"] for r in rows("offers.jsonl")]
out_d1 = rows("outcomes.jsonl")
st_d = live.offer_status(offer_d["id"])
print(f"[D1] outcomes = {[(r['outcome'], r.get('choice')) for r in out_d1]}")
print(f"[D1] offers.jsonl results = {res_d1}")
print(f"[D1] offer_status(id) = {st_d!r}  已结论 = {st_d in live.SETTLED_OFFER_STATES}")


def script_d2(win, pump):
    d_info["msg"] = win.msg.get("text")
    d_info["buttons"] = win._buttons()
    pump(8)


drive(script_d2)
reasked = "别再问了" in str(d_info.get("msg"))
D_OK = (st_d == "rejected" and st_d in live.SETTLED_OFFER_STATES and not reasked
        and len(EXECUTED) == 0)
print(f"[D2] 重启后气泡文本 = {d_info.get('msg')!r}")
print(f"[D2] 又被问了一遍？ = {reasked}")
print(f"[D2] 结论: {'PASS' if D_OK else 'FAIL'}")

print("\n" + "=" * 72)
print(f"四场景总结果: A={A_OK} B={B_OK} C={C_OK} D={D_OK}")
print("=" * 72)