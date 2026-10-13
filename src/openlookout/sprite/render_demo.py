"""把压力演示渲染成一张图：真实 tkinter 气泡（xvfb 下截图）+ 日志面板。python -m sprite.render_demo DEMO_JSON OUT.png"""
import json, os, sys, tempfile, textwrap, time
from pathlib import Path

def main(demo_json, out):
    import tkinter as tk
    from PIL import ImageGrab, Image, ImageDraw, ImageFont
    from .gui import SpriteWindow
    d = json.loads(Path(demo_json).read_text("utf-8"))
    says = [m for m in d["messages"] if m["kind"] == "say"]
    root = tk.Tk(); root.geometry("1000x600+0+0"); root.configure(bg="#eef2f3")
    shots = []
    for i in range(2):                       # 第 0 次是预热（首个窗口常常来不及映射）
        w = SpriteWindow(root, Path(tempfile.mkdtemp()), lambda *a, **k: None, lambda *a: None, lambda: None)
        w.sx, w.sy = 800, 300; w.state = "thinking"; w.frame = 1; w.msg = says[0]
        w.redraw(); root.update(); time.sleep(0.6); root.update()
        x, y, ww, wh = w.win.winfo_rootx(), w.win.winfo_rooty(), w.win.winfo_width(), w.win.winfo_height()
        shots.append(ImageGrab.grab(bbox=(x - 4, y - 4, x + ww + 4, y + wh + 4), xdisplay=os.environ.get("DISPLAY"))); w.win.destroy(); root.update()
    shots = shots[1:]
    font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 15)
    lines = ["【小精灵这次做了什么（压力事件：内存 1.0/16GB、C: 剩 1.0/20GB）】", ""]
    for m in d["messages"]:
        tag = {"say": "说", "action": "已做", "undo": "撤销"}[m["kind"]]
        lines += textwrap.wrap(f"[{tag}] {m['text']}", 44) + [""]
    lines += ["【陷阱检查】被改动的陷阱文件：%s" % (d["trap_changed"] or "无"), "被挂起的进程：%s（前台标签104、播放音乐105、未保存Word 106、IDE、node服务均未动）" % d["suspended_pids"],
              "撤销后清理项全部还原：%s；用户切回浏览器后标签进程已恢复：%s" % (d["safes_restored"], d["resumed_on_foreground"])]
    H = max(len(lines) * 22 + 40, shots[0].height + 60)
    img = Image.new("RGB", (shots[0].width + 780, H), "white"); img.paste(shots[0], (10, 30)); dr = ImageDraw.Draw(img)
    dr.text((10, 5), "气泡（真实 tkinter 渲染）", fill="#000", font=font)
    y = 10
    for l in lines: dr.text((shots[0].width + 30, y), l, fill="#111", font=font); y += 22
    img.save(out); print(out, img.size)

if __name__ == "__main__": main(*sys.argv[1:3])
