"""“内存爆炸”触发器：真实分配并写入（touch）内存，把可用内存压到小精灵的告警阈值以下。
安全：永远给系统留 ≥1.5GB 可用（硬编码下限，参数也不能更低）；自动超时释放（默认 240 秒）；红色置顶窗口带“停止并释放”按钮（Esc 也行）；关闭窗口/Ctrl+C 即释放。
python -m sprite.demo_live.eat_memory [--mb N] [--leave-gb G] [--timeout S] [--no-gui]"""
from __future__ import annotations
import argparse, sys, time
from .common import EAT_FLOOR_GB, load_demo_cfg, home_dir, eat_target_avail_gb, mem_now

CHUNK_MB = 64


class Eater:
    def __init__(self, leave_gb: float, mb: int | None = None, mem=mem_now):
        self.leave = max(EAT_FLOOR_GB, leave_gb); self.want = mb; self.mem = mem; self.chunks = []; self.stopped = False
    @property
    def held_mb(self): return len(self.chunks) * CHUNK_MB
    def step(self) -> bool:
        """再吃一块；返回是否还要继续。"""
        if self.stopped: return False
        if self.want is not None and self.held_mb >= self.want: return False
        total, avail = self.mem()
        if (avail - CHUNK_MB) / 1024 < self.leave: return False           # 再吃就低于下限：停
        b = bytearray(CHUNK_MB * 2**20); b[::4096] = b"\x01" * len(range(0, len(b), 4096))      # 每页都写一下，真正占用物理内存
        self.chunks.append(b); return True
    def release(self): self.chunks.clear(); self.stopped = True


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--mb", type=int); ap.add_argument("--leave-gb", type=float); ap.add_argument("--timeout", type=float, default=240); ap.add_argument("--no-gui", action="store_true")
    a = ap.parse_args(argv)
    total, avail = mem_now(); dc = load_demo_cfg(home_dir())
    leave = a.leave_gb if a.leave_gb is not None else eat_target_avail_gb(total, dc)
    e = Eater(leave, a.mb); t0 = time.time()
    print(f"内存 {total/1024:.1f}GB，当前可用 {avail/1024:.1f}GB；目标：可用降到约 {max(leave, EAT_FLOOR_GB):.1f}GB（下限 {EAT_FLOOR_GB}GB），{a.timeout:.0f} 秒后自动释放。", flush=True)
    if a.no_gui:
        try:
            while time.time() - t0 < a.timeout:
                if not e.step(): time.sleep(0.5)
        except KeyboardInterrupt: pass
        e.release(); return
    import tkinter as tk
    root = tk.Tk(); root.title("内存爆炸演示（点停止即释放）"); root.attributes("-topmost", True); root.configure(bg="#b3261e"); root.geometry("+40+40")
    lab = tk.Label(root, text="", fg="white", bg="#b3261e", font=("Microsoft YaHei", 13, "bold"), justify="left"); lab.pack(padx=18, pady=(14, 6))
    def stop(*_): e.release(); root.destroy()
    tk.Button(root, text="停止并立刻释放内存", command=stop, font=("Microsoft YaHei", 14, "bold"), bg="white", fg="#b3261e", padx=14, pady=8).pack(padx=18, pady=(4, 16))
    root.bind("<Escape>", stop); root.protocol("WM_DELETE_WINDOW", stop)
    def tick():
        left = a.timeout - (time.time() - t0)
        if left <= 0: stop(); return
        grew = 0
        while grew < 4 and e.step(): grew += 1               # 每次最多 256MB，保持界面响应
        _, av = mem_now()
        lab.config(text=f"正在占用 {e.held_mb/1024:.1f} GB 内存（真实分配）\n系统可用 {av/1024:.1f} GB（目标 {max(leave, EAT_FLOOR_GB):.1f} GB，硬下限 1.5 GB）\n{left:.0f} 秒后自动释放")
        root.after(150 if grew else 500, tick)
    root.after(50, tick); root.mainloop(); e.release()


if __name__ == "__main__":
    main()
