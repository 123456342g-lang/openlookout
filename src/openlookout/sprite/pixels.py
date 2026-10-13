"""小精灵的像素形象（青色猫脸）。纯数据，无 tkinter，可无头测试。状态：idle / observing / working / thinking。
每个状态由 基础脸 + 表情覆盖层 + 帧动画 组成。坐标 14x13 格。"""
CYAN, DARK, WHITE, PINK, GRAY = "#27c9d6", "#12353a", "#ffffff", "#ff9bb0", "#8fb7bb"

BASE = [
    "..#........#..",
    ".###......###.",
    ".############.",
    "##############",
    "##############",
    "##############",
    "##############",
    "##############",
    "##############",
    "##############",
    ".############.",
    "..##########..",
    "..............",
]
# 眼睛左右中心 (x,y)
EYES = [(4, 6), (9, 6)]


def render(state: str, frame: int = 0, blink: bool = False):
    """返回 [(x, y, color)] 格子列表。frame 为动画帧（整数递增）。"""
    cells = [(x, y, CYAN) for y, row in enumerate(BASE) for x, ch in enumerate(row) if ch == "#"]
    cells += [(2, 1, PINK), (11, 1, PINK)]                     # 耳内
    ex = 0
    if state == "observing": ex = 1 if (frame // 3) % 2 == 0 else -1   # 左右张望
    for (x, y) in EYES:
        if blink and state != "working":
            cells += [(x - 1, y + 1, DARK), (x, y + 1, DARK)]            # 眨眼：一条线
        elif state == "working":
            cells += [(x - 1, y + 1, DARK), (x, y, DARK), (x + 1, y + 1, DARK)]   # ^ ^ 专注
        elif state == "thinking":
            cells += [(x, y, DARK), (x, y + 1, DARK), (x - 1, y, WHITE)]    # 睁大眼（高光）
        else:
            cells += [(x + ex, y, DARK), (x + ex, y + 1, DARK)]
    # 嘴
    if state == "idle": cells += [(6, 9, DARK), (7, 9, DARK)]
    elif state == "observing": cells += [(6, 9, DARK), (7, 9, DARK)]
    elif state == "working": cells += [(5, 9, DARK), (6, 10, DARK), (7, 10, DARK), (8, 9, DARK)]
    elif state == "thinking": cells += [(7, 9, DARK), (8, 9, DARK)]          # 抿嘴偏一侧
    # 装饰
    if state == "thinking":
        cells += [(13, 0, GRAY)] if frame % 2 == 0 else [(12, 0, GRAY), (13, 0, GRAY)]   # 想事情的泡泡点
        cells += [(10, 4, DARK), (11, 4, DARK)]                                          # 一条眉毛
    if state == "working":
        d = frame % 4; cells += [(13, 12 - d, WHITE)]                                      # 干活的小火花
    if state == "observing":
        cells += [(13, 5, WHITE), (13, 6, GRAY)]                                          # 放大镜柄点
    return cells


STATES = ("idle", "observing", "working", "thinking")
W, H = 14, 13
