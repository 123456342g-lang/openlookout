"""气泡 + 小精灵窗口（tkinter canvas，只在 GUI 入口导入 tkinter）。
设计：
- 无边框置顶窗口，精灵永远在窗口一角；有话时窗口向左（贴近屏幕左缘时向右）长出一个气泡，气泡尾巴指向精灵。
- 精灵与气泡共用同一套硬边“像素风”：精灵按整数倍放大，气泡用圆角、实色、2px 描边。tkinter 画布没有抗锯齿，所以不做渐变和斜线，避免毛边和风格不一致。
- 气泡里只有一行话 + 2~3 个小按钮（或 好/撤销）；没有输入框；自动消失。
- 拖动精灵移动，位置记在 sprite_pos.json。眨眼、各状态动画。
- 布局计算是纯函数（layout），可无头测试。

T3 真实 Windows 修正：
- 进程声明 per-monitor v2 DPI 感知，高缩放下不再被系统位图拉伸（模糊/错位）；
- 布局按“虚拟屏幕矩形”（多显示器）钳制：左右缘、上下缘都考虑，气泡不出屏；
- 先画气泡/尾巴、后画精灵，尾巴尖端收进精灵边缘，视觉上“指向精灵”而非盖住精灵；
- 几何字符串用带符号格式（负坐标不再生成 "+-30" 这种非法 Tk 语法）；
- 工具窗口（-toolwindow）+ 不调用 focus_force，不抢焦点。"""
from __future__ import annotations
import ctypes, json, queue, random, sys
from pathlib import Path
from .pixels import render, W, H

SCALE = 5
FONT = ("Microsoft YaHei", 10)
BG, EDGE, TXT, BTN, BTN_TXT = "#ffffff", "#12353a", "#12353a", "#d6f5f8", "#12353a"
PAD, TAIL = 10, 9


def _clamp(v, lo, hi):
    return max(lo, min(v, hi))


def _geo(x, y):
    """把屏幕偏移格式化成 Tk 几何后缀（负号写法正确）：(+30+50) / (-30+50)。"""
    return f"{x:+d}{y:+d}"


def enable_dpi_awareness():
    """让本进程按显示器 DPI 感知（per-monitor v2），否则 Windows 会把窗口位图拉伸（模糊+错位）。
    必须在创建任何窗口前调用；同一进程只能设置一次；失败静默降级。"""
    if sys.platform != "win32":
        return
    try:
        u32 = ctypes.windll.user32
        if u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):   # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        shcore.SetProcessDpiAwareness(2)                             # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        pass


def screen_rect(root):
    """虚拟屏幕矩形 (x0, y0, w, h)，覆盖所有显示器；失败退回 tk 主屏。"""
    try:
        if sys.platform == "win32":
            u32 = ctypes.windll.user32
            x = u32.GetSystemMetrics(76); y = u32.GetSystemMetrics(77)
            w = u32.GetSystemMetrics(78); h = u32.GetSystemMetrics(79)
            if w and h:
                return (x, y, w, h)
    except Exception:
        pass
    return (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())


def layout(text_w, text_h, n_btn_w, screen_w, sprite_x, sprite_size=(W * SCALE, H * SCALE),
           *, screen_rect_=None, sprite_y=0):
    """纯函数：返回 dict(side, bubble=(x0,y0,x1,y1), tail=[(x,y)*3])，坐标相对“精灵左上角”。

    气泡紧贴精灵（间距=TAIL）、垂直居中于精灵头部；优先放在空间大的一侧，并钳制在
    screen_rect_（虚拟屏幕矩形，默认 (0,0,screen_w,4*精灵高)）内：靠近左缘→右边，
    靠近右缘→左边；两边都放不下→放空间大的一侧并贴边。尾巴尖端落在精灵边缘，
    尾巴 y 始终落在气泡垂直范围内。"""
    sw, sh = sprite_size
    sx0, sy0, sww, shh = screen_rect_ or (0, 0, screen_w, sh * 4)
    bw = max(text_w, n_btn_w) + 2 * PAD
    bh = text_h + 2 * PAD + (24 if n_btn_w else 0)
    room_l = sprite_x - sx0                        # 精灵左侧空间
    room_r = (sx0 + sww) - (sprite_x + sw)         # 精灵右侧空间
    if room_l >= bw + TAIL and room_r < bw + TAIL:
        side = "left"
    elif room_r >= bw + TAIL and room_l < bw + TAIL:
        side = "right"
    elif room_l >= room_r:
        side = "left"
    else:
        side = "right"
    # 水平（相对精灵坐标；留 2px 边距，保证气泡不出屏）
    left_edge, right_edge = sx0 - sprite_x + 2, sx0 + sww - sprite_x - 2
    if side == "left":
        x1 = -TAIL; x0 = x1 - bw; tip = 2
    else:
        x0 = sw + TAIL; x1 = x0 + bw; tip = sw - 2
    if x0 < left_edge:
        x0 = left_edge; x1 = x0 + bw
    if x1 > right_edge:
        x1 = right_edge; x0 = x1 - bw
    # 垂直：高气泡底与精灵底对齐（向上长），普通气泡居中于精灵；再钳制到屏幕内
    y0 = sh // 2 - bh // 2
    if bh > sh:
        y0 = sh - bh
    y0 = _clamp(y0, sy0 - sprite_y + 2, sy0 + shh - sprite_y - 2 - bh)
    ty = _clamp(sh // 3, y0 + 3, y0 + bh - 3)
    tail = [(x1, ty - 5), (x1, ty + 5), (tip, ty)] if side == "left" else [(x0, ty - 5), (x0, ty + 5), (tip, ty)]
    return dict(side=side, bubble=(x0, y0, x1, y0 + bh), tail=tail)


def load_pos(home: Path):
    f = Path(home) / "sprite_pos.json"
    try: return tuple(json.loads(f.read_text())["pos"])
    except Exception: return None


def save_pos(home: Path, x, y): (Path(home) / "sprite_pos.json").write_text(json.dumps({"pos": [x, y]}))


def rounded(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


class SpriteWindow:
    def __init__(self, root, home: Path, on_choice, on_undo, on_expire):
        import tkinter as tk, tkinter.font as tkf
        self.tk, self.root, self.home = tk, root, Path(home)
        self.on_choice, self.on_undo, self.on_expire = on_choice, on_undo, on_expire
        enable_dpi_awareness()
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        try: self.win.attributes("-toolwindow", True)     # Windows：不进任务栏/Alt-Tab，避免抢焦点
        except tk.TclError: pass
        self.win.attributes("-topmost", True)
        self.trans = "#fe00fe"
        try: self.win.attributes("-transparentcolor", self.trans)       # Windows 透明底；Linux 下退化为纯色底
        except tk.TclError: self.trans = "#e8f6f7"
        self._noact_done = False
        self.win.after(120, self._apply_noactivate)   # 窗口映射后再设 NOACT（见方法注释）
        self.c = tk.Canvas(self.win, highlightthickness=0, bg=self.trans); self.c.pack()
        self.font = tkf.Font(family=FONT[0], size=FONT[1])
        self.screen_rect = screen_rect(root)
        sx0, sy0, sww, shh = self.screen_rect
        pos = load_pos(home)
        if pos and sx0 - 20 <= pos[0] <= sx0 + sww - 20 and sy0 - 20 <= pos[1] <= sy0 + shh - 20:
            self.sx, self.sy = pos                     # 多显示器：只有位置在虚拟屏内才沿用
        else:
            self.sx, self.sy = sx0 + sww - 120, sy0 + shh - 160   # 默认在虚拟屏右下角
        self.state, self.frame, self.msg, self.drag = "idle", 0, None, None
        self.hide_job = None; self.blink = False; self.ox = self.oy = 0
        self.c.bind("<ButtonPress-1>", self._press); self.c.bind("<B1-Motion>", self._move); self.c.bind("<ButtonRelease-1>", self._release)
        self.redraw()
        self.win.after(300, self._tick); self.win.after(random.randint(2500, 5000), self._blink)

    def _apply_noactivate(self):
        """WS_EX_NOACTIVATE(0x08000000)：窗口永远不成为前台窗口（含被点击时不激活），不抢焦点。
        必须在窗口映射后设置：Tk 首次显示窗口时会按内部状态整体重写扩展样式，把该位清掉。"""
        if self._noact_done:
            return
        self._noact_done = True
        try:
            # winfo_id 是 Tk 的子窗口，向上回溯到真正的顶层（TkTopLevel 包装窗口）
            hwnd = int(self.win.winfo_id())
            while True:
                parent = ctypes.windll.user32.GetParent(hwnd)
                if not parent:
                    break
                hwnd = parent
            gwl = -20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl)
            ctypes.windll.user32.SetWindowLongW(hwnd, gwl, style | 0x08000000)
        except Exception:
            pass

    def set_state(self, s):
        if s != self.state: self.state = s; self.redraw()

    def show(self, msg: dict, seconds: int):
        self.msg = msg; self.redraw()
        if self.hide_job: self.win.after_cancel(self.hide_job)
        wait = seconds * (5 if msg.get("options") else 1)      # 带选项的话多留一会儿
        self.hide_job = self.win.after(wait * 1000, lambda: self.hide(expired=True))

    def hide(self, expired=False):
        if self.msg and expired: self.on_expire()
        self.msg = None; self.redraw()

    def _buttons(self):
        m = self.msg
        if not m: return []
        det = [("详情", ("detail", None))] if m.get("detail") else []
        if m.get("options"): return [(o, ("choice", i)) for i, o in enumerate(m["options"][: (2 if det else 3)])] + det
        if m.get("action_id"): return [("撤销", ("undo", m["action_id"])), ("好", ("ok", None))] + det
        if det: return det
        return []

    def redraw(self):
        c = self.c; c.delete("all"); tk = self.tk
        sw, sh = W * SCALE, H * SCALE
        total_w, left_pad, top_pad = sw + 6, 0, 6
        geo = None
        if self.msg:
            tid = c.create_text(0, 0, text=self.msg["text"], font=self.font, width=210, anchor="nw")
            bb = c.bbox(tid); c.delete(tid)
            btns = self._buttons()
            bw = sum(self.font.measure(t) + 20 for t, _ in btns) + 6 * max(0, len(btns) - 1)
            geo = layout(bb[2] - bb[0], bb[3] - bb[1], bw, self.screen_rect[2], self.sx,
                         screen_rect_=self.screen_rect, sprite_y=self.sy)
            x0, y0, x1, y1 = geo["bubble"]
            left_pad = max(0, -x0) + 2; total_w = max(sw, x1) + left_pad + 4; top_pad = max(0, -y0) + 4
        total_h = max(sh, geo["bubble"][3] if geo else 0) + top_pad + 4
        c.config(width=total_w, height=total_h)
        ox, oy = left_pad, top_pad                                 # 精灵左上角在画布里的位置
        self.ox, self.oy = ox, oy
        # 1) 先画气泡、尾巴与文字（尾巴尖端收进精灵边缘下面）
        if geo:
            x0, y0, x1, y1 = geo["bubble"]
            rounded(c, ox + x0, oy + y0, ox + x1, oy + y1, 10, fill=BG, outline=EDGE, width=2)
            t = [(ox + x, oy + y) for x, y in geo["tail"]]
            c.create_polygon(t, fill=BG, outline=EDGE, width=2)
            sx = ox + x0 + PAD
            # 盖住尾巴与气泡接缝处的描边
            bx = ox + (geo["tail"][0][0])
            c.create_line(bx, oy + geo["tail"][0][1] + 2, bx, oy + geo["tail"][1][1] - 2, fill=BG, width=3)
            c.create_text(sx, oy + y0 + PAD, text=self.msg["text"], font=self.font, width=210, anchor="nw", fill=TXT)
            bx0 = sx; by = oy + y1 - PAD - 18
            for t_, act in self._buttons():
                w = self.font.measure(t_) + 20
                r = rounded(c, bx0, by, bx0 + w, by + 20, 8, fill=BTN, outline=EDGE, width=1)
                tx = c.create_text(bx0 + w / 2, by + 10, text=t_, font=self.font, fill=BTN_TXT)
                for item in (r, tx): c.tag_bind(item, "<Button-1>", lambda e, a=act: self._click(a))
                bx0 += w + 6
        # 2) 后画精灵本体：盖住尾巴尖端，视觉上尾巴“指向”并收进精灵边缘
        for (x, y, col) in render(self.state, self.frame, self.blink):
            c.create_rectangle(ox + x * SCALE, oy + y * SCALE, ox + (x + 1) * SCALE, oy + (y + 1) * SCALE, fill=col, outline=col)
        self.win.geometry(_geo(self.sx - ox, self.sy - oy))

    def _click(self, act):
        kind, v = act
        if kind == "detail":
            self.msg = dict(self.msg, text=self.msg["detail"], detail=None); self.redraw(); return
        if kind == "choice": self.on_choice(v)
        elif kind == "undo": self.on_undo(v)
        else: self.on_choice(None, ok=True)
        self.hide(expired=False)

    # 拖动
    def _press(self, e):
        if self.ox <= e.x <= self.ox + W * SCALE and self.oy <= e.y <= self.oy + H * SCALE:
            self.drag = (e.x_root - self.sx, e.y_root - self.sy)
    def _move(self, e):
        if self.drag: self.sx, self.sy = e.x_root - self.drag[0], e.y_root - self.drag[1]; self.win.geometry(_geo(self.sx - self.ox, self.sy - self.oy))
    def _release(self, e):
        if self.drag: self.drag = None; save_pos(self.home, self.sx, self.sy); self.redraw()

    def _tick(self):
        self.frame += 1; self.redraw() if self.state != "idle" else None
        self.win.after(300, self._tick)
    def _blink(self):
        self.blink = True; self.redraw(); self.win.after(140, self._unblink)
    def _unblink(self):
        self.blink = False; self.redraw(); self.win.after(random.randint(2500, 6000), self._blink)


def run_gui(sprite, seconds: int, poll_s: float, should_quit=None):
    import tkinter as tk
    enable_dpi_awareness()
    q: queue.Queue = queue.Queue()
    sprite.on_message = lambda m: q.put(m) if m.get("kind") == "say" else None
    root = tk.Tk(); root.withdraw()
    def on_choice(i, ok=False): sprite.respond(i if not ok else 0)
    w = SpriteWindow(root, sprite.home, on_choice, lambda aid: (sprite.undo(aid), sprite.respond(0)), lambda: sprite.respond(None, kind="ignore"))
    def loop():
        try: sprite.tick()
        except Exception as e: print("tick error:", e)
        try:
            while True: w.show(q.get_nowait(), seconds)
        except queue.Empty: pass
        w.set_state(sprite.mood)
        if should_quit and should_quit(): root.destroy(); return
        root.after(int(poll_s * 1000), loop)
    root.after(100, loop); root.mainloop()
