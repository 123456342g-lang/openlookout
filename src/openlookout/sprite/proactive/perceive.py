"""持续感知层：一直在后台记录“你现在在做什么”的原始证据，不调用任何模型。
- 每 SAMPLE_S 秒读一次：前台窗口（标题、进程名）、距上次键鼠输入的秒数。
- 屏幕相对上次有明显变化才存一张压缩截图（静止时不占空间）。
- 所有数据只在本机 perceive/ 目录；超过 RETAIN_H 小时的截图和日志自动删除，总大小超过 MAX_MB 也从最旧的删起。
- now.json 始终是最新一条，给理解层和气泡读取。
python -m sprite.proactive.perceive [--seconds N]    不加 --seconds 则一直运行，Ctrl+C 结束。
"""
from __future__ import annotations
import argparse, ctypes, json, os, time
from ctypes import wintypes as W
from datetime import datetime
from pathlib import Path

import psutil
from PIL import Image, ImageGrab

HOME = Path(os.environ.get("SPRITE_HOME", r"E:\OpenLookout\sprite_home"))
DIR = HOME / "perceive"
FRAMES = DIR / "frames"
LOG = DIR / "log.jsonl"
NOW = DIR / "now.json"

SAMPLE_S = 5              # 采样间隔
CHANGE_MIN = 0.02         # 屏幕缩略图平均像素差超过 2% 才算“变了”
FORCE_FRAME_S = 300       # 即使没变，也每 5 分钟存一张，保证时间线连续
RETAIN_H = 24             # 保留时长
MAX_MB = 2048             # 总大小上限
CLEAN_EVERY_S = 600
THUMB = (48, 30)          # 变化检测用的缩略图
SHOT_WIDTH = 960          # 存档截图宽度
SHOT_QUALITY = 60


class LastInput(ctypes.Structure):
    _fields_ = [("cbSize", W.UINT), ("dwTime", W.DWORD)]


def idle_seconds() -> float:
    info = LastInput(ctypes.sizeof(LastInput), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000


def foreground() -> dict:
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd: return {"title": "", "proc": ""}
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(hwnd, buf, n + 1)
    pid = W.DWORD(); u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try: proc = psutil.Process(pid.value).name()
    except psutil.Error: proc = ""
    return {"title": buf.value, "proc": proc}


def screen_thumb(img: Image.Image) -> list[int]:
    return list(img.convert("L").resize(THUMB).getdata())


def changed(a: list[int] | None, b: list[int]) -> bool:
    if a is None: return True
    diff = sum(abs(x - y) for x, y in zip(a, b)) / (len(a) * 255)
    return diff >= CHANGE_MIN


def save_frame(img: Image.Image, ts: datetime) -> str:
    FRAMES.mkdir(parents=True, exist_ok=True)
    name = ts.strftime("%Y%m%d-%H%M%S") + ".jpg"
    w = SHOT_WIDTH; h = int(img.height * w / img.width)
    img.convert("RGB").resize((w, h)).save(FRAMES / name, "JPEG", quality=SHOT_QUALITY)
    return name


def append_log(row: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_now(row: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = NOW.with_suffix(".tmp"); tmp.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, NOW)


def cleanup(now: float) -> dict:
    """删除超过保留时长的截图和日志行；再按总大小从最旧的删起。"""
    cutoff = now - RETAIN_H * 3600
    if FRAMES.exists():
        for f in FRAMES.glob("*.jpg"):
            if f.stat().st_mtime < cutoff: f.unlink()
    if LOG.exists():
        keep = [L for L in LOG.read_text(encoding="utf-8").splitlines() if L and json.loads(L)["t"] >= cutoff]
        LOG.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    frames = sorted(FRAMES.glob("*.jpg")) if FRAMES.exists() else []
    total = sum(f.stat().st_size for f in frames)
    while frames and total > MAX_MB * 2**20:
        old = frames.pop(0); total -= old.stat().st_size; old.unlink()
    return dict(frames=len(frames), mb=round(total / 2**20, 1))


def run(seconds: float | None = None) -> None:
    start = time.time(); last_thumb = None; last_frame_t = 0.0; last_clean = 0.0
    while seconds is None or time.time() - start < seconds:
        t = time.time(); ts = datetime.fromtimestamp(t)
        fg = foreground(); idle = idle_seconds()
        img = ImageGrab.grab()
        thumb = screen_thumb(img)
        frame = None
        if changed(last_thumb, thumb) or t - last_frame_t >= FORCE_FRAME_S:
            frame = save_frame(img, ts); last_frame_t = t
        last_thumb = thumb
        row = dict(t=t, time=ts.isoformat(timespec="seconds"), title=fg["title"], proc=fg["proc"], idle_s=round(idle, 1), frame=frame)
        append_log(row); write_now(row)
        if t - last_clean >= CLEAN_EVERY_S:
            last_clean = t; cleanup(t)
        time.sleep(max(0.0, SAMPLE_S - (time.time() - t)))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--seconds", type=float)
    a = ap.parse_args(argv)
    try: run(a.seconds)
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
