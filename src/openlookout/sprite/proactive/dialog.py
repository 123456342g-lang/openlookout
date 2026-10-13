"""点小精灵弹出的对话框：白底、深青边框，和气泡同一套配色。
用 pack 自动排版，文字换行后整体变高，不会互相重叠；对话框始终贴在小精灵上方。
- 标题行：小精灵 + 右上角 ×
- 状态：小精灵当前的判断（灰色小字）
- 回应：发送后它的回应（深色正文），对话框保持打开
- 输入：输入框 + 发送按钮；回车发送，Esc 关闭
"""
from __future__ import annotations
import tkinter as tk
from datetime import datetime
from typing import Callable

from ..gui import BG, BTN, BTN_TXT, EDGE, FONT, TXT

CARD_W, PAD, GAP = 360, 14, 12
MUTED, SOFT = "#5a7b80", "#d6f5f8"
INPUT_BG = "#f4fbfc"


class ChatDialog:
    def __init__(self, root: tk.Tk, anchor_x: int, anchor_y: int, status: str,
                 on_send: Callable[[str], str], history: list[dict] | None = None):
        self.anchor = (anchor_x, anchor_y); self.on_send = on_send
        self.win = tk.Toplevel(root); self.win.overrideredirect(True); self.win.attributes("-topmost", True)
        self.win.configure(bg=EDGE)
        card = tk.Frame(self.win, bg=BG, padx=PAD, pady=PAD); card.pack(padx=2, pady=2)

        head = tk.Frame(card, bg=BG); head.pack(fill="x")
        tk.Label(head, text="小精灵", bg=BG, fg=TXT, font=(FONT[0], 10, "bold")).pack(side="left")
        close = tk.Label(head, text="×", bg=BG, fg=MUTED, font=(FONT[0], 13), cursor="hand2")
        close.pack(side="right"); close.bind("<Button-1>", lambda _e: self.close())
        tk.Frame(card, bg=SOFT, height=1).pack(fill="x", pady=(6, 8))

        self.status = tk.Label(card, text=status, bg=BG, fg=MUTED, font=(FONT[0], 9), wraplength=CARD_W - 2 * PAD, justify="left", anchor="w")
        self.status.pack(fill="x")
        history_frame = tk.Frame(card, bg=BG)
        history_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.history_box = tk.Text(history_frame, height=11, width=40, wrap="word", state="disabled",
                                   bg=INPUT_BG, fg=TXT, relief="flat", padx=8, pady=6,
                                   font=(FONT[0], 9), highlightthickness=1, highlightbackground=EDGE)
        scroll = tk.Scrollbar(history_frame, command=self.history_box.yview)
        self.history_box.configure(yscrollcommand=scroll.set)
        self.history_box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        row = tk.Frame(card, bg=BG); row.pack(fill="x", pady=(10, 0))
        self.ent = tk.Entry(row, font=(FONT[0], 10), relief="flat", bg=INPUT_BG, fg=TXT, insertbackground=TXT,
                            highlightthickness=1, highlightbackground=EDGE, highlightcolor=EDGE)
        self.ent.pack(side="left", fill="x", expand=True, ipady=4)
        self.btn = tk.Button(row, text="发送", bg=BTN, fg=BTN_TXT, activebackground=BTN, relief="flat", bd=0,
                             font=(FONT[0], 10), padx=12, pady=3, command=self.send, cursor="hand2")
        self.btn.pack(side="left", padx=(8, 0))
        tk.Label(card, text="回车发送 · Esc 关闭", bg=BG, fg=MUTED, font=(FONT[0], 8)).pack(anchor="w", pady=(6, 0))

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
        who = "我" if role == "user" else "小精灵"
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
                who = "我" if role == "user" else "小精灵"
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
