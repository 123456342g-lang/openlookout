"""在 xvfb 下真实渲染 SpriteWindow 的各状态并截图（用 PIL ImageGrab）。python -m sprite.render_states OUT.png"""
import os, sys, subprocess, tempfile
from pathlib import Path

def main(out):
    import tkinter as tk
    from PIL import ImageGrab, Image, ImageDraw
    from .gui import SpriteWindow
    root = tk.Tk(); root.geometry("1000x700+0+0"); root.configure(bg="#eef2f3")
    msgs = {"idle": None, "observing": None, "working": None,
            "thinking": dict(text="这点我和你看法不太一样：语音助手我看它其实在原地打转（把握约 90%），依据是成果 前两周 2 → 后两周 0。当然你定。", options=["我再想想", "我有你不知道的信息", "维持现状"])}
    extra = {"report": dict(text="刚才给 lab7 建好了子文件夹和说明。", action_id="x")}
    shots = []
    home = Path(tempfile.mkdtemp())
    items = [("warm", None)] + list(msgs.items()) + list(extra.items())
    for i, (name, m) in enumerate(items):
        state = name if name in msgs else "idle"
        if name == "warm": state = "idle"
        w = SpriteWindow(root, home, lambda *a, **k: None, lambda *a: None, lambda: None)
        w.win.after_cancel  # noqa
        w.blink = False
        w.sx, w.sy = 560 if name != "thinking" else 700, 300
        w.state = state; w.frame = 1
        if m: w.msg = m
        w.redraw(); root.update(); import time; time.sleep(0.6); root.update(); root.update_idletasks()
        x, y = w.win.winfo_rootx(), w.win.winfo_rooty(); ww, wh = w.win.winfo_width(), w.win.winfo_height()
        img = ImageGrab.grab(bbox=(x - 4, y - 4, x + ww + 4, y + wh + 4), xdisplay=os.environ.get("DISPLAY"))
        if i > 0: shots.append((name, img))
        w.win.destroy(); root.update()
    W_ = sum(i.width for _, i in shots) + 20 * (len(shots) + 1); H_ = max(i.height for _, i in shots) + 60
    sheet = Image.new("RGB", (W_, H_), "#ffffff"); d = ImageDraw.Draw(sheet); x = 20
    for name, im in shots:
        sheet.paste(im, (x, 40)); d.text((x, 10), name, fill="#000"); x += im.width + 20
    sheet = sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST)
    sheet.save(out); print(out, sheet.size)

if __name__ == "__main__": main(sys.argv[1])
