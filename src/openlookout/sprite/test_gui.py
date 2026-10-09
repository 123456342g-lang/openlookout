"""T3 无头测试：布局（多显示器/左右缘/上下缘钳制、尾巴指向）、几何格式、像素四状态。不依赖 tkinter。"""
import json
from pathlib import Path
from sprite.gui import layout, _geo, load_pos, save_pos
from sprite.pixels import render, W, H, STATES, CYAN, DARK, WHITE, PINK, GRAY

SCREEN = (0, 0, 1707, 1067)          # 本机虚拟屏
SPRITE = (W * 5, H * 5)              # 70 x 65


def near_edges():
    """精灵贴近左/右缘时，气泡应放对面一侧。"""
    left = layout(120, 20, 60, SCREEN[2], 10, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    assert left["side"] == "right"
    right = layout(120, 20, 60, SCREEN[2], SCREEN[2] - 90, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    assert right["side"] == "left"


def test_layout_side_choice_near_edges():
    near_edges()
    # 中间偏左：左侧空间不够放整气泡 -> 右边
    g = layout(200, 20, 60, SCREEN[2], 80, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    assert g["side"] == "right"
    # 两边都放得下：放空间大的一侧
    g = layout(100, 20, 0, SCREEN[2], 800, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    assert g["side"] == "left" if 800 >= SCREEN[2] - 800 - SPRITE[0] else g["side"] == "right"


def test_layout_no_overlap_when_room():
    """空间足够时，气泡与精灵之间有 TAIL 间距，尾巴尖端落在精灵边缘。"""
    g = layout(100, 20, 0, SCREEN[2], 800, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    x0, y0, x1, y1 = g["bubble"]
    assert x1 == -9 or x0 == SPRITE[0] + 9        # 紧贴精灵（间距=TAIL）
    tip = g["tail"][2]
    assert tip[0] in (2, SPRITE[0] - 2)           # 尖端在精灵边缘
    assert y0 <= tip[1] <= y1                     # 尾巴 y 落在气泡垂直范围内


def test_layout_clamps_right_edge():
    """气泡过大且精灵偏右时，气泡必须钳制在屏幕右缘内（相对坐标）。"""
    g = layout(400, 300, 200, SCREEN[2], 1200, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    x0, y0, x1, y1 = g["bubble"]
    assert x1 <= SCREEN[0] + SCREEN[2] - 1200 - 2 + 0.5      # 屏幕右缘 - 精灵x - 2px 边距
    assert g["side"] == "left"


def test_layout_clamps_right_edge_when_screen_narrow():
    """屏幕比“精灵+气泡”还窄时（气泡宽于整个屏幕），右缘必须锚定在屏幕右缘内；
    左侧越界是不可避免的（气泡本身比屏宽）。"""
    rect = (0, 0, 200, 1067)
    g = layout(260, 20, 0, 200, 150, SPRITE, screen_rect_=rect, sprite_y=500)
    x0, x1 = g["bubble"][0], g["bubble"][2]
    right_edge = rect[0] + rect[2] - 150 - 2
    assert x1 <= right_edge + 0.5                       # 气泡右缘不出屏
    assert x0 <= x1                                     # 几何自洽
    assert g["side"] == "left"


def test_layout_multi_monitor_negative_x():
    """副屏在主屏左边（虚拟屏 x 为负）：气泡选空间大的一侧且不出该屏范围。"""
    rect = (-1920, 0, 1920, 1080)
    g = layout(160, 20, 0, 1920, -1500, SPRITE, screen_rect_=rect, sprite_y=500)
    assert g["side"] == "right"
    x0, x1 = g["bubble"][0], g["bubble"][2]
    assert x0 >= rect[0] - (-1500) + 2 - 0.5
    assert x1 <= rect[0] + rect[2] - (-1500) - 2 + 0.5


def test_layout_vertical_clamp_top_and_bottom():
    """高气泡在屏幕顶部/底部都被钳制，不出屏。"""
    rect = (0, 0, 1707, 1067)
    # 精灵贴顶：高气泡底对齐精灵底 -> 再钳制，顶部至少留 2px
    g = layout(100, 220, 0, 1707, 800, SPRITE, screen_rect_=rect, sprite_y=5)
    assert g["bubble"][1] >= rect[1] - 5 + 2 - 0.5
    # 精灵贴底：气泡底部不超过屏幕底
    g = layout(100, 60, 0, 1707, 800, SPRITE, screen_rect_=rect, sprite_y=1000)
    assert g["bubble"][3] <= rect[1] + rect[3] - 1000 - 2 + 0.5


def test_layout_scales_with_text_size():
    """字更大（模拟 125%/150% DPI 下字体变大）时气泡随之变大，且仍不出屏。"""
    base = layout(100, 20, 0, 1707, 300, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    big = layout(100, 20 * 1.5, 0, 1707, 300, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    assert big["bubble"][3] - big["bubble"][1] > base["bubble"][3] - base["bubble"][1]
    # 超长话（整屏宽）：气泡仍被钳制在屏幕内
    g = layout(2000, 800, 300, 1707, 800, SPRITE, screen_rect_=SCREEN, sprite_y=500)
    assert g["bubble"][2] <= SCREEN[0] + SCREEN[2] - 800 - 2 + 0.5


def test_geo_sign_formatting():
    assert _geo(30, 50) == "+30+50"
    assert _geo(-30, 50) == "-30+50"
    assert _geo(30, -50) == "+30-50"
    assert _geo(-30, -50) == "-30-50"
    assert _geo(0, 0) == "+0+0"


def test_load_save_pos(tmp_path):
    save_pos(tmp_path, 100, 200)
    assert load_pos(tmp_path) == (100, 200)
    assert json.loads((tmp_path / "sprite_pos.json").read_text())["pos"] == [100, 200]
    (tmp_path / "sprite_pos.json").write_text("broken{")
    assert load_pos(tmp_path) is None


def test_pixels_states_use_palette_and_animate():
    palette = {CYAN, DARK, WHITE, PINK, GRAY}
    for s in STATES:
        for f in (0, 1, 2, 3):
            cells = render(s, f)
            assert cells, s
            assert all(c[2] in palette for c in cells), (s, f)
    # observing：左右张望，帧会变
    assert render("observing", 0) != render("observing", 3)
    # working：有火花
    assert any(c == (13, 12, WHITE) for c in render("working", 0))
    # thinking：有思考泡泡点与眉毛
    assert any(c[2] == GRAY for c in render("thinking", 0))
    # 眨眼：idle 时眼睛变一条线
    assert render("idle", 0, blink=True) != render("idle", 0, blink=False)
