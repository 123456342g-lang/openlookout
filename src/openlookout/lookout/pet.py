"""A tiny animated desktop companion with a single-line conversation box."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from queue import Empty, Queue
import threading
import time

from .pet_runtime import Inbox, InstanceLock, Recorder, snapshot_events


class Sprite:
    def __init__(self, root, repo: Path, interval: int = 60, start: bool = False):
        import tkinter as tk

        self.tk, self.root = tk, root
        self.repo = repo.resolve()
        self.home = self.repo / "data" / "pet"
        self.events_path = self.home / "capture" / "events.jsonl"
        self.interval = max(15, interval)
        self.recorder = Recorder(self.repo, self.home)
        self.inbox = Inbox(self.home)
        self.results = Queue()
        self.reply_results = Queue()
        self.running = self.analysis_running = self.closed = False
        self.generation = 0
        self.last_analysis = 0.0
        self.last_signature = None
        self.current_id = None
        self.current_item = None
        self.notice = ""
        self.frame_index = 0
        self.chat_open = False
        self.chat_window = None
        self.chat_frame = None
        self.entry = None
        self.reply = None
        self.last_spoken_event = None
        self.last_spoken_at = 0.0

        root.title("小望")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg="#010101")
        try:
            root.attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(root, width=104, height=104, bg="#010101", highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", lambda event: self.toggle_chat())
        self.canvas.bind("<Button-3>", lambda event: self.hide_chat())
        root.bind("<Escape>", lambda event: self.hide_chat())
        root.bind("<Control-q>", lambda event: self.close())
        self.place_orb()
        self.animate()
        if start:
            self.start()
            root.after(900, self.start_prompt)
        self.tick_id = root.after(500, self.tick)

    def place_orb(self):
        x = max(0, self.root.winfo_screenwidth() - 140)
        y = max(0, self.root.winfo_screenheight() - 190)
        self.root.geometry(f"104x104+{x}+{y}")

    def animate(self):
        if self.closed:
            return
        self.frame_index += 1
        self.draw_pet()
        self.root.after(180, self.animate)

    def draw_pet(self):
        import math

        self.canvas.delete("all")
        bob = int(math.sin(self.frame_index / 5) * 3)
        attention = self.current_item is not None
        body = "#ffb86c" if attention else "#8be9fd"
        self.canvas.create_oval(13, 78 + bob, 91, 100 + bob, fill="#000000", outline="")
        self.canvas.create_oval(14, 14 + bob, 90, 90 + bob, fill=body, outline="#ffffff", width=2)
        self.canvas.create_polygon(25, 24 + bob, 28, 7 + bob, 43, 20 + bob, fill=body, outline="#ffffff")
        self.canvas.create_polygon(61, 20 + bob, 76, 7 + bob, 79, 25 + bob, fill=body, outline="#ffffff")
        blink = self.frame_index % 37 in (0, 1)
        if blink:
            self.canvas.create_line(33, 48 + bob, 42, 48 + bob, fill="#17202a", width=3)
            self.canvas.create_line(62, 48 + bob, 71, 48 + bob, fill="#17202a", width=3)
        else:
            self.canvas.create_oval(32, 41 + bob, 43, 55 + bob, fill="#17202a", outline="")
            self.canvas.create_oval(61, 41 + bob, 72, 55 + bob, fill="#17202a", outline="")
            self.canvas.create_oval(35, 43 + bob, 38, 46 + bob, fill="white", outline="")
            self.canvas.create_oval(64, 43 + bob, 67, 46 + bob, fill="white", outline="")
        self.canvas.create_arc(43, 50 + bob, 61, 68 + bob, start=200, extent=140, style="arc", outline="#17202a", width=2)

    def toggle_chat(self):
        self.show_chat() if not self.chat_open else self.hide_chat()

    def start_prompt(self):
        if self.running and not self.chat_open:
            self.last_spoken_at = time.monotonic()
            self.show_chat("我在这里。你现在在做什么？我可以帮你把它往前推一步。")

    def show_chat(self, prompt=None):
        if self.chat_open:
            return
        import tkinter as tk

        self.chat_open = True
        self.chat_window = tk.Toplevel(self.root)
        self.chat_window.title("小望")
        self.chat_window.overrideredirect(True)
        self.chat_window.attributes("-topmost", True)
        self.chat_window.configure(bg="#010101")
        try:
            self.chat_window.attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass
        x = max(0, self.root.winfo_x() - 285)
        y = max(0, self.root.winfo_y() - 18)
        self.chat_window.geometry(f"300x132+{x}+{y}")
        self.chat_window.bind("<Escape>", lambda event: self.hide_chat())
        cloud = tk.Canvas(self.chat_window, width=300, height=132, bg="#010101", highlightthickness=0)
        cloud.pack(fill="both", expand=True)
        cloud.create_oval(8, 22, 90, 102, fill="white", outline="white")
        cloud.create_oval(45, 7, 145, 103, fill="white", outline="white")
        cloud.create_oval(102, 18, 215, 108, fill="white", outline="white")
        cloud.create_oval(178, 30, 285, 110, fill="white", outline="white")
        cloud.create_polygon(42, 92, 18, 124, 83, 100, fill="white", outline="white")
        self.chat_frame = tk.Frame(self.chat_window, bg="white", padx=12, pady=8)
        self.chat_frame.place(x=48, y=31, width=205, height=76)
        self.reply = tk.Label(self.chat_frame, text=prompt or self.prompt_text(), bg="white", fg="#34495e",
                              anchor="w", justify="left", wraplength=180, font=("Segoe UI", 9))
        self.reply.pack(fill="x", pady=(0, 6))
        self.entry = tk.Entry(self.chat_frame, bg="white", fg="#17202a", relief="flat",
                              highlightthickness=1, highlightbackground="#d9e2ec", font=("Segoe UI", 10))
        self.entry.pack(fill="x", ipady=5)
        self.entry.bind("<Return>", self.send_message)
        self.entry.focus_set()

    def hide_chat(self):
        if not self.chat_open:
            return
        self.chat_open = False
        if self.chat_window:
            self.chat_window.destroy()
        self.chat_window = self.chat_frame = self.entry = self.reply = None

    def prompt_text(self):
        if self.current_item:
            if self.current_item.get("judgment", {}).get("state") == "ask":
                return "我有一点不确定。你现在更想解决哪件事？"
            return "我发现一个可能帮得上的地方，要我先试试吗？"
        if self.notice:
            return self.notice
        return "你在忙什么？告诉我，我来帮你往前推。"

    def send_message(self, event=None):
        text = self.entry.get().strip() if self.entry else ""
        if not text:
            return "break"
        self.inbox.append("conversation.jsonl", {"ts": time.time(), "role": "user", "text": text})
        lowered = text.lower()
        if self.current_id:
            action = None
            if any(word in lowered for word in ("有用", "可以", "试试", "继续")):
                action = "useful"
            elif any(word in lowered for word in ("不对", "不是", "不相关")):
                action = "not_relevant"
            elif any(word in lowered for word in ("知道", "明白", "已经")):
                action = "already_known"
            elif any(word in lowered for word in ("晚点", "稍后")):
                action = "later"
            if action:
                self.inbox.feedback(self.current_id, action)
                self.current_id = None
                self.current_item = None
                self.notice = "收到。我会结合之后发生的事重新判断。"
            else:
                self.notice = "我想一下，先找一个最小的下一步。"
                if self.reply:
                    self.reply.configure(text=self.notice)
                threading.Thread(target=self.answer_message, args=(text, self.current_item), daemon=True).start()
        else:
            self.notice = "我想一下，看看现在从哪一步开始最省力。"
            if self.reply:
                self.reply.configure(text=self.notice)
            threading.Thread(target=self.answer_message, args=(text, None), daemon=True).start()
        self.inbox.append("conversation.jsonl", {"ts": time.time(), "role": "assistant", "text": self.notice})
        self.entry.delete(0, "end")
        if self.reply:
            self.reply.configure(text=self.notice)
        self.draw_pet()
        return "break"

    def answer_message(self, text, item):
        fallback = "先把你想得到的结果写成一句话，再找一个十分钟内能验证的最小动作。"
        try:
            from .llm import LLM

            system = ("你是一个常驻桌面伙伴。只用简洁中文回答，最多三句话。"
                      "根据用户当前问题和有限行为线索，给出一个可马上开始、可回退的最小下一步；"
                      "不假装已经替用户完成操作，不输出技术细节，不连续追问。")
            payload = {"message": text, "observed_candidate": item or {}}
            llm = LLM(self.home / "conversation", "mimo-v2.6-flash")
            answer, _ = llm.chat("pet_conversation", system, json.dumps(payload, ensure_ascii=False),
                                 max_tokens=260, temperature=0.2)
            answer = answer.strip() or fallback
        except Exception:
            answer = fallback
        self.reply_results.put(answer)

    def start(self):
        if self.running:
            return
        try:
            self.recorder.start()
        except (OSError, RuntimeError) as error:
            self.notice = f"暂时没法开始陪伴：{error}"
        else:
            self.running = True
            self.generation += 1
            self.last_signature = None
            self.last_analysis = 0
            self.notice = "我在看着。"

    def stop(self):
        self.running = False
        self.generation += 1
        self.recorder.stop()
        self.notice = "我先休息一下。"

    def tick(self):
        if self.closed:
            return
        try:
            while True:
                answer = self.reply_results.get_nowait()
                self.notice = answer
                if self.chat_open and self.reply:
                    self.reply.configure(text=answer)
        except Empty:
            pass
        try:
            while True:
                generation, signature, summary, error = self.results.get_nowait()
                self.analysis_running = False
                if generation != self.generation:
                    continue
                self.last_signature = signature
                self.notice = "我会先自己判断，只有需要你决定时才来问你。" if not error else "刚才没看清，我会再试一次。"
                if not error:
                    self.inbox.merge(summary)
        except Empty:
            pass
        if self.running and not self.recorder.active:
            self.running = False
            self.notice = "我暂时离开了，点我可以重新开始。"
        if self.running and time.monotonic() - self.last_analysis >= self.interval:
            self.check_events()
        previous_id = self.current_id
        attention = [item for item in self.inbox.pending()
                     if item.get("judgment", {}).get("state") in {"act", "ask"}]
        self.current_item = attention[0] if attention else None
        self.current_id = self.current_item.get("id") if self.current_item else None
        if self.current_id and self.current_id != previous_id and not self.chat_open:
            self.last_spoken_at = time.monotonic()
            self.show_chat("我发现一个值得你知道的地方。你现在想把它往哪边推进？")
        elif self.running and not self.chat_open:
            self.consider_activity_prompt()
        self.draw_pet()
        if self.chat_open and self.reply and not self.entry.get():
            self.reply.configure(text=self.prompt_text())
        self.tick_id = self.root.after(1000, self.tick)

    def consider_activity_prompt(self):
        if time.monotonic() - self.last_spoken_at < 180:
            return
        if not self.events_path.exists():
            return
        try:
            rows = []
            with self.events_path.open("rb") as stream:
                for raw in stream.readlines()[-30:]:
                    if raw.strip():
                        rows.append(json.loads(raw.decode("utf-8")))
        except (OSError, ValueError, UnicodeDecodeError):
            return
        if not rows:
            return
        latest = rows[-1]
        key = (latest.get("ts"), latest.get("type"), latest.get("path"), latest.get("title"), latest.get("dur_s"))
        if self.last_spoken_event is None:
            self.last_spoken_event = key
            return
        if key == self.last_spoken_event:
            return
        prompt = None
        if latest.get("type") == "focus" and int(latest.get("dur_s") or 0) >= 180:
            prompt = "你刚刚专注了一段时间。刚才完成了什么？下一步准备做什么？"
        elif latest.get("type") in {"file_save", "file_open"}:
            prompt = "我看到你刚完成了一步。你想把结果整理好，还是继续往下做？"
        elif latest.get("type") == "focus":
            apps = [row.get("app") for row in rows[-8:] if row.get("type") == "focus" and row.get("app")]
            if len(set(apps)) >= 4:
                prompt = "你刚才在几个地方来回切换，是卡住了吗？我可以先帮你拆出第一步。"
        if prompt:
            self.last_spoken_event = key
            self.last_spoken_at = time.monotonic()
            self.notice = prompt
            self.show_chat(prompt)

    def signature(self):
        result = []
        for path in (self.events_path, self.home / "corrections.jsonl"):
            stat = path.stat() if path.exists() else None
            result.append((stat.st_size, stat.st_mtime_ns) if stat else (0, 0))
        return tuple(result)

    def check_events(self, force=False):
        if self.analysis_running:
            return
        signature = self.signature()
        if not force and signature == self.last_signature:
            return
        self.last_analysis = time.monotonic()
        self.analysis_running = True
        threading.Thread(target=self.analyze, args=(self.generation, signature), daemon=True).start()

    def analyze(self, generation, signature):
        try:
            from .trajectory import run

            capture = self.home / "analysis_capture"
            window = snapshot_events(self.events_path, capture)
            summary = run(capture, self.home / "trajectory", corrections_path=self.home / "corrections.jsonl")
            summary["stats"].update(window)
            self.results.put((generation, signature, summary, None))
        except Exception as error:
            self.results.put((generation, signature, None, str(error)[:180]))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.running = False
        self.generation += 1
        if self.tick_id:
            self.root.after_cancel(self.tick_id)
        self.recorder.stop()
        self.root.destroy()


def main(argv=None):
    import tkinter as tk
    from tkinter import messagebox

    parser = argparse.ArgumentParser(description="OpenLookout 桌面精灵")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    root = tk.Tk()
    try:
        lock = InstanceLock(repo / "data" / "pet" / "instance.lock")
    except (RuntimeError, ImportError) as error:
        messagebox.showinfo("小望", str(error), parent=root)
        root.destroy()
        return
    sprite = None
    try:
        sprite = Sprite(root, repo, args.interval, args.start)
        root.mainloop()
    finally:
        if sprite:
            sprite.recorder.stop()
        lock.close()


if __name__ == "__main__":
    main()
