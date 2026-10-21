"""点小精灵弹出的对话框：白底、深青边框，和气泡同一套配色。
用 pack 自动排版，文字换行后整体变高，不会互相重叠；对话框始终贴在小精灵上方。
- 标题行：小精灵 + 右上角 ×
- 状态：小精灵当前的判断（灰色小字）
- 待回应：气泡消失时没看见的提议，在这里补点「好的/不用」（issue #26）
- 回应：发送后它的回应（深色正文），对话框保持打开
- 输入：输入框 + 发送按钮；回车发送，Esc 关闭
"""
from __future__ import annotations
import tkinter as tk
from datetime import datetime
from typing import Callable

from ..gui import BG, BTN, BTN_TXT, EDGE, FONT, TXT
from ..i18n import t

# 卡片宽度与字号。原先 CARD_W=360 配 9号字，一屏放不下几句话，字号也偏小；
# 放大到 480/12号 后一屏能看完整段对话，且不用眯眼。
CARD_W, PAD, GAP = 480, 16, 12
BODY_FONT = 12# 对话正文 / 输入框字号（跟随气泡的 14 号略微收一档）
HEAD_FONT = 13
MUTED, SOFT = "#5a7b80", "#d6f5f8"
INPUT_BG = "#f4fbfc"


class ChatDialog:
    def __init__(self, root: tk.Tk, anchor_x: int, anchor_y: int, status: str,
                 on_send: Callable[[str], str], history: list[dict] | None = None,
                 pending: list[dict] | None = None,
                 on_decide: Callable[[dict, bool], None] | None = None):
        self.anchor = (anchor_x, anchor_y); self.on_send = on_send
        self.on_decide = on_decide
        self.win = tk.Toplevel(root); self.win.overrideredirect(True); self.win.attributes("-topmost", True)
        self.win.configure(bg=EDGE)
        card = tk.Frame(self.win, bg=BG, padx=PAD, pady=PAD); card.pack(padx=2, pady=2)

        head = tk.Frame(card, bg=BG); head.pack(fill="x")
        tk.Label(head, text=t("title"), bg=BG, fg=TXT,
                 font=(FONT[0], HEAD_FONT, "bold")).pack(side="left")
        close = tk.Label(head, text="×", bg=BG, fg=MUTED, font=(FONT[0], HEAD_FONT + 3), cursor="hand2")
        close.pack(side="right"); close.bind("<Button-1>", lambda _e: self.close())
        tk.Frame(card, bg=SOFT, height=1).pack(fill="x", pady=(6, 8))

        self.status = tk.Label(card, text=status, bg=BG, fg=MUTED, font=(FONT[0], BODY_FONT),
                               wraplength=CARD_W - 2 * PAD, justify="left", anchor="w")
        self.status.pack(fill="x")
        # 错过气泡 ≠ 拒绝：补点窗口（默认 2h）内的未决提议摆在这里，点了走与气泡
        # 点头完全相同的执行链（issue #26）。
        if pending:
            self._build_pending(card, pending)
        history_frame = tk.Frame(card, bg=BG)
        history_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.history_box = tk.Text(history_frame, height=13, width=52, wrap="word", state="disabled",
                                   bg=INPUT_BG, fg=TXT, relief="flat", padx=8, pady=6,
                                   font=(FONT[0], BODY_FONT), highlightthickness=1,
                                   highlightbackground=EDGE)
        scroll = tk.Scrollbar(history_frame, command=self.history_box.yview)
        self.history_box.configure(yscrollcommand=scroll.set)
        self.history_box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        row = tk.Frame(card, bg=BG); row.pack(fill="x", pady=(10, 0))
        self.ent = tk.Entry(row, font=(FONT[0], BODY_FONT), relief="flat", bg=INPUT_BG, fg=TXT,
                            insertbackground=TXT, highlightthickness=1,
                            highlightbackground=EDGE, highlightcolor=EDGE)
        self.ent.pack(side="left", fill="x", expand=True, ipady=5)
        self.btn = tk.Button(row, text=t("send"), bg=BTN, fg=BTN_TXT, activebackground=BTN, relief="flat", bd=0,
                             font=(FONT[0], BODY_FONT), padx=12, pady=3, command=self.send, cursor="hand2")
        self.btn.pack(side="left", padx=(8, 0))
        tk.Label(card, text=t("hint"), bg=BG, fg=MUTED,
                 font=(FONT[0], BODY_FONT - 3)).pack(anchor="w", pady=(6, 0))

        self.ent.bind("<Return>", lambda _e: self.send()); self.win.bind("<Escape>", lambda _e: self.close())
        self.set_history(history or [])
        self.win.after(50, self._focus)
        self._place()

    def _alive(self, *widgets: str) -> bool:
        """True only while the toplevel, the named widgets, and the app are all up.

        为什么不能直接写 ``if not self.win.winfo_exists()``：
        ``winfo_exists`` 本身就是一次 Tcl 调用。整个 Tk 应用被销毁后它不再返回 0，
        而是抛 ``TclError: can't invoke "winfo" command: application has been destroyed``——
        守卫自己先炸，等于没有守卫（Tk 已死时任何 ``.win.*`` 调用都会这样）。
        所以判断必须连自己的失败一起吞掉。
        """
        try:
            if not self.win.winfo_exists():
                return False
            return all(getattr(self, name).winfo_exists() for name in widgets)
        except tk.TclError:
            return False

    def _build_pending(self, parent: tk.Widget, offers: list[dict]) -> None:
        """「它刚问你的事」：错过的提议在补点窗口内可在这里点头或拒绝。"""
        box = tk.Frame(parent, bg=BG)
        box.pack(fill="x", pady=(10, 0))
        tk.Label(box, text=t("pending_header"), bg=BG, fg=MUTED,
                 font=(FONT[0], BODY_FONT - 2), anchor="w").pack(fill="x")
        for offer in list(offers)[-3:]:
            self._add_pending_card(box, offer)

    def _add_pending_card(self, box: tk.Widget, offer: dict) -> None:
        card = tk.Frame(box, bg=INPUT_BG, highlightbackground=EDGE, highlightthickness=1)
        card.pack(fill="x", pady=(6, 0))
        tk.Label(card, text=str(offer.get("text") or "")[:200], bg=INPUT_BG, fg=TXT,
                 font=(FONT[0], BODY_FONT), wraplength=CARD_W - 2 * PAD - 24,
                 justify="left", anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        row = tk.Frame(card, bg=INPUT_BG)
        row.pack(fill="x", padx=10, pady=(0, 8))

        def choose(approved: bool) -> None:
            if not self._alive():
                return
            try:
                if self.on_decide is not None:
                    self.on_decide(offer, approved)
            except Exception as exc:  # 落账/执行链异常不能把对话框带崩
                print(f"pending decide error: {type(exc).__name__}: {exc}", flush=True)
                return
            try:
                card.destroy()
            except tk.TclError:
                return
            self._place()

        tk.Button(row, text=t("accept"), bg=BTN, fg=BTN_TXT, activebackground=BTN,
                  relief="flat", bd=0, font=(FONT[0], BODY_FONT - 1),
                  padx=14, pady=2, cursor="hand2",
                  command=lambda: choose(True)).pack(side="left")
        tk.Button(row, text=t("decline"), bg="#e7f0f1", fg=MUTED, activebackground="#d8e6e8",
                  relief="flat", bd=0, font=(FONT[0], BODY_FONT - 1),
                  padx=14, pady=2, cursor="hand2",
                  command=lambda: choose(False)).pack(side="left", padx=(8, 0))

    def _place(self) -> None:
        """按内容实际高度，把对话框底边放在小精灵上方。"""
        if not self._alive():
            return
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = max(self.anchor[0] - 20, 0); y = max(self.anchor[1] - h - GAP, 0)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def _focus(self) -> None:
        # 这是 win.after(50) 回调：用户 50ms 内点 × 关掉窗口，回调就打在已销毁控件上。
        if not self._alive("ent"):
            return
        self.win.focus_force(); self.ent.focus_set()

    def send(self) -> None:
        if not self._alive("ent"):
            return
        text = self.ent.get().strip()
        if not text: return
        self.ent.delete(0, tk.END)
        response = self.on_send(text)
        self._append_local("user", text)
        if response:
            self._append_local("assistant", response)
        self._place()

    def _append_local(self, role: str, text: str) -> None:
        if not self._alive("history_box"):
            return
        self.history_box.configure(state="normal")
        stamp = datetime.now().strftime("%H:%M")
        who = t("me") if role == "user" else t("sprite")
        self.history_box.insert(tk.END, f"{stamp}  {who}\n{text.strip()}\n\n")
        self.history_box.configure(state="disabled")
        self.history_box.see(tk.END)

    def set_history(self, rows: list[dict]) -> None:
        if not self._alive("history_box"):
            return
        self.history_box.configure(state="normal")
        self.history_box.delete("1.0", tk.END)
        for row in rows[-80:]:
            role = row.get("role", "assistant")
            text = str(row.get("text") or "").strip()
            if text:
                stamp = str(row.get("time") or "")[-8:-3] or datetime.now().strftime("%H:%M")
                who = t("me") if role == "user" else t("sprite")
                self.history_box.insert(tk.END, f"{stamp}  {who}\n{text}\n\n")
        self.history_box.configure(state="disabled")
        self.history_box.see(tk.END)

    def set_status(self, text: str) -> None:
        if not self._alive("status"):
            return
        self.status.config(text=text); self._place()

    def close(self) -> None:
        # 幂等：已销毁就什么都不做，重复 close / Tk 已死都不该抛。
        if not self._alive():
            return
        self.win.destroy()
