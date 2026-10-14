"""气泡不能占着屏幕不放，也不能让精灵只说一次。

真实反馈（10-13 17:03~17:09）：「感觉它就启动一次，启动一次说一次话，就不再说了
或者隔很久，好像缺少了某个回路，而且同一句话会显示很久，这不合理。」

两句话对应两个独立缺陷，本文件把它们各自钉住：

**同一句话显示很久** —— 三处写死的时长。
``present(..., 180)`` 让一句 20 字的话在屏幕上钉三分钟；待机提示
``w.show(..., 3600)`` 让一句引导语挂一小时；``gui.show`` 对带 options 的气泡
再乘 5，把「好的/不用」变成十分钟。读一句话要几秒，占着屏幕一小时不是体贴。

**只说一次就不再说了** —— 回路缺口。
``HEARTBEAT_S`` 是屏幕静止时**唯一**能唤醒循环的触发源（screen/window/timing
都不 fire），它曾是 900s。更糟的是心跳轮被提示词引导成「默认安静」，
于是屏幕一静，精灵就被自己的提示词锁死——心跳调短也救不回来，必须一起改。
"""
from __future__ import annotations

import ast
import inspect
import json
import re
import time
from pathlib import Path

import pytest

import sprite.proactive.live as live
import vista.benchmarks.desktop.brain as brain
import vista.benchmarks.desktop.watching as watching

BRAIN = Path(live.__file__).resolve().parents[2] / "vista" / "benchmarks" / "desktop" / "brain.py"
GUI = Path(live.__file__).resolve().parents[1] / "gui.py"


def _src(path: Path) -> str:
    return path.read_text("utf-8")


# ---------------------------------------------------------------- 气泡时长

def test_bubble_duration_scales_with_the_sentence():
    """一句话该留多久由它有多长决定，不是写死的常数。"""
    short = live.bubble_seconds("刚吃完饭回来")
    long = live.bubble_seconds("这是一段很长的汇报，需要列出三处改动和两条路径，" * 3)
    assert long > short
    assert short >= live.BUBBLE_READ_S


def test_bubble_duration_is_bounded_above():
    """再长的句子也有上限：气泡不是告示牌。"""
    huge = live.bubble_seconds("啊" * 5000)
    assert huge <= live.BUBBLE_MAX_S
    assert huge < 120, "超长文本也要收住，别在屏幕上钉成常驻"


def test_bubble_duration_has_a_readable_floor():
    """太短会读不完——下限必须存在，且明显长于「扫一眼」的量级。"""
    assert live.BUBBLE_READ_S >= 10, "一句话至少要留够读完的时间"
    assert live.bubble_seconds("") >= live.BUBBLE_READ_S


def test_offer_bubble_is_not_ten_minutes_of_waiting():
    """带选项的气泡会被 gui 再乘一次系数，所以这里的基数必须小。"""
    effective = live.OFFER_ASK_S * 2          # gui.show 现在只 ×2
    assert effective <= 360, f"点头决定实际要等 {effective}s，太久了"


def test_offer_effective_lifetime_is_two_minutes_not_five():
    """issue #11 新发现 2：注释曾把 60×2 算成 300s，实际是 120s。

    人眼验收目标就是「offer 约 120s 消失」，这里把实际算式钉死，
    注释再写错也会被这条测试戳穿。
    """
    assert live.OFFER_ASK_S * 2 == 120


def test_show_s_constant_is_gone_for_good():
    """SHOW_S=3600 早已没有调用点，删除后不许以任何形式回来。"""
    assert not hasattr(live, "SHOW_S"), "写死一小时的 SHOW_S 已删除，不要复活它"


def test_no_source_site_passes_a_bare_hundred_eighty_seconds():
    """companion 气泡不能写死 180s：一句短话钉三分钟正是实测到的现象。"""
    tree = ast.parse(_src(Path(live.__file__)))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "present":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, (int, float)) and node.args[1].value >= 120:
                offenders.append(node.lineno)
    assert not offenders, f"这些行把气泡时长写死成 >=120s：{offenders}"


def test_idle_hint_does_not_outlive_a_full_hour():
    """待机提示曾经是 3600s，屏幕上挂着一句它从未说过的话。"""
    tree = ast.parse(_src(Path(live.__file__)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "show":
            for arg in node.args[1:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
                    assert arg.value <= 300, f"第 {node.lineno} 行待机气泡超过 300s"
                # 名字里带 IDLE 的走变量，直接排除常量路径
                if isinstance(arg, ast.Name) and "HINT" in arg.id:
                    continue


def test_idle_hint_is_not_logged_as_something_the_sprite_said():
    """引导语不是精灵的发言，不能进 transcript——否则模型会以为自己说过。"""
    src = _src(Path(live.__file__))
    assert "IDLE_HINT_TEXT" in src
    assert re.search(r"if text and text != IDLE_HINT_TEXT:", src), \
        "present 必须按常量过滤待机提示，不能留着旧的硬编码字符串"


def test_gui_does_not_multiply_options_by_five():
    """gui.show 原来对 options 乘 5，是「十分钟等一个点头」的放大器。"""
    src = _src(GUI)
    assert "(5 if msg.get(\"options\") else 1)" not in src, \
        "带选项气泡的 ×5 系数必须收掉，否则上面调小基数也没用"
    assert "* (2 if msg.get(\"options\") else 1)" in src


# ---------------------------------------------------------------- 回路缺口

def test_heartbeat_is_short_enough_to_be_a_real_loop():
    """心跳是屏幕静止时唯一的唤醒源。900s 意味着最长静默一刻钟。"""
    import vista.benchmarks.desktop.brain as brain
    assert brain.HEARTBEAT_S <= 300, \
        f"兜底心跳 {brain.HEARTBEAT_S}s 太长，屏幕一静就没有轮次可醒"


def test_heartbeat_stays_above_one_turn():
    """心跳不能小于一轮真实耗时（30~100s），否则退化成连续排队。"""
    import vista.benchmarks.desktop.brain as brain
    assert brain.HEARTBEAT_S > brain.TURN_TIMEOUT_S / 3, \
        "心跳与单轮耗时同量级会互相排队"
    assert brain.MIN_GAP_S < brain.HEARTBEAT_S


def test_heartbeat_turn_is_not_an_opening_license():
    """10-13 晚实测翻车：旧文案写「不需要先取证也能说的日常短话此刻就成立」，
    心跳轮立刻产出「九点多……今天这一天挺长的」——时间到了不构成事由。

    新契约两头都钉：不许「默认安静」（watching 真报卡住/来回翻时它该说），
    也不许「不取证也能说」（时间感慨许可证），必须明写时间不是开口理由。
    """
    prompt = brain.heartbeat_note(240)
    assert "默认安静" not in prompt, \
        "计时事实真报卡住/来回翻时应该能说话，不能整体默认安静"
    assert "不需要先取证" not in prompt and "不取证" not in prompt, \
        "心跳轮不得再发「不取证也能说」的开口许可证（10-13 实测的废话来源）"
    assert "时间到了本身不是开口理由" in prompt, \
        "心跳轮必须明写：时间流逝不是开口事由"
    assert "一律 quiet" in prompt, "时间/天色/辛苦感慨必须明确归为 quiet"


def test_heartbeat_turn_lead_does_not_call_it_a_preparation_round():
    """叫「背景准备轮」本身就在带偏：那一轮首先是重新看一眼状态。"""
    src = _src(BRAIN)
    assert 'lead = "这是本次背景准备轮。"' not in src
    assert "兜底心跳轮" in src


def test_no_hardcoded_hour_anywhere_in_the_bubble_path():
    """兜底：气泡路径上不允许再出现写死一小时这种量级的时长。

    只查**代码**，不查注释——注释里解释「原来这里是 3600，所以改掉了」是
    有价值的，把注释一起扫会让这条测试变成不许说话。
    """
    for path in (Path(live.__file__), GUI):
        for number, line in enumerate(_src(path).splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"(?<!\d)3600(?!\d)", code):
                pytest.fail(f"{path.name}:{number} 代码里还有写死的 3600：{line.strip()}")


# ------------------------------------------------------ 心跳文案数字语义（b）

def test_heartbeat_note_minutes_are_the_real_turn_gap():
    """「距上一轮判断 X 分钟」必须代入距上轮的真实秒数，不是键鼠 idle。

    旧代码把 current_idle_s（GetLastInputInfo：键鼠无输入时长）代进去，
    人一直敲键盘但屏幕静止、和人走开十分钟，都会让这个数字说谎。
    """
    assert "4 分钟" in brain.heartbeat_note(240)
    assert "9 分钟" in brain.heartbeat_note(540)
    # 时钟异常给负值也不许炸，更不许显示成负的分钟数
    assert "0 分钟" in brain.heartbeat_note(-5)


def test_heartbeat_note_body_cannot_see_keyboard_idle():
    """钉死语义来源：heartbeat_note 的函数体里不许出现 idle 变量。

    只查函数体不查 docstring——docstring 必须解释「为什么不能用 idle」。
    """
    tree = ast.parse(_src(BRAIN))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "heartbeat_note")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert not ({"idle_s", "current_idle_s"} & names), \
        "心跳文案的分钟数只能来自 turn_gap_s，碰 idle 就是旧 bug 复发"


# --------------------------------------------- 心跳分支排除 reply/away（c）

_AWAY = watching.DEFAULTS["away_s"]          # 300s：watching.py 的离开阈值


def _hb_kw(**over):
    kw = dict(heartbeat_due=True, turn_gap_s=240, idle_s=10.0, reply_pending=False,
              fb="", return_due=False, continue_due=False, goal_due=False,
              has_visual=False)
    kw.update(over)
    return kw


def test_heartbeat_window_opens_on_a_plain_quiet_heartbeat():
    """人在、无回话义务、无锚点、无新画面的心跳轮：心跳提示成立（但提示本身
    已不再是开口许可证，内容契约由 test_heartbeat_turn_is_not_an_opening_license 钉）。"""
    note = brain.heartbeat_note_if_due(**_hb_kw())
    assert note and "兜底心跳轮" in note


def test_heartbeat_window_suppressed_when_visual_attached():
    """900s 兜底的带图心跳有新 CURRENT 可看：心跳文案明说「本轮没有新画面」，
    附图时附它就是说谎，必须让位给正常带图轮提示。"""
    assert brain.heartbeat_note_if_due(**_hb_kw(has_visual=True)) == ""


def test_heartbeat_window_suppressed_while_reply_pending():
    """他在等回话时，心跳鼓励不得与【优先回话】叠加。"""
    assert brain.heartbeat_note_if_due(**_hb_kw(reply_pending=True)) == ""


@pytest.mark.parametrize("idle_s", [_AWAY, _AWAY + 120])
def test_heartbeat_window_suppressed_when_away(idle_s):
    """键鼠无输入达到/超过 watching.away_s（300s）：让位给「别打扰」事实。"""
    assert brain.heartbeat_note_if_due(**_hb_kw(idle_s=idle_s)) == ""


def test_heartbeat_window_open_right_under_the_away_threshold():
    """边界：差 1 秒到 away 阈值时仍然是心跳窗口（阈值由 watching 单一持有）。"""
    assert brain.heartbeat_note_if_due(**_hb_kw(idle_s=_AWAY - 1))


@pytest.mark.parametrize("field,value", [
    ("heartbeat_due", False), ("fb", "用户刚刚对你说了话"),
    ("return_due", True), ("continue_due", True), ("goal_due", "goal-1"),
])
def test_heartbeat_window_suppressed_for_anchored_turns(field, value):
    """没到心跳、或本轮已有真实锚点：心跳文案不叠加（锚点各有自己的提示词）。"""
    assert brain.heartbeat_note_if_due(**_hb_kw(**{field: value})) == ""


def test_away_fact_still_carries_the_do_not_disturb_line():
    """心跳分支让位的前提：away 轮的 watching 事实里确实有「别打扰」。"""
    line = watching.Watching(away=True, away_s=_AWAY).line()
    assert "别打扰" in line and "回来再说" in line


def test_quiet_fallback_is_also_suppressed_for_reply_turns():
    """回话轮已被要求「不要 quiet」，背景静默分支也不得再补一句「默认安静」。"""
    src = _src(BRAIN)
    assert "elif not reply_pending and not (fb or return_due or continue_due or goal_due):" in src, \
        "默认安静分支必须显式排除 reply_pending，否则和优先回话自相矛盾"


# ---------------------------------- 高频感知 / 低频带图：两级模型轮（10-13 晚反馈）

_VW_BASE = dict(screen_due=False, window_due=False, timing_due=False, fb="",
                return_due=False, reply_due=False,
                now=1000.0, last_visual_turn=1000.0)


@pytest.mark.parametrize("field", [
    "screen_due", "window_due", "timing_due", "return_due", "reply_due",
])
def test_visual_tier_strong_signals_request_a_fresh_image(field):
    """强视觉/强交互信号：必须带新截图（翻书、切窗、操作断点、回来、有人等回话）。"""
    kw = dict(_VW_BASE)
    kw[field] = True
    assert brain.turn_wants_visual(**kw) is True


def test_visual_tier_user_feedback_requests_a_fresh_image():
    kw = dict(_VW_BASE); kw["fb"] = "他说了句话"
    assert brain.turn_wants_visual(**kw) is True


def test_visual_tier_plain_heartbeat_within_recheck_is_text_only():
    """什么事都没有、只是 240s 心跳到了：无图文本轮。图像 token 归零，
    watching 的计时事实是纯文本，照样能判断该不该说话。"""
    kw = dict(_VW_BASE)
    kw["now"] = kw["last_visual_turn"] + brain.HEARTBEAT_S
    assert brain.turn_wants_visual(**kw) is False


def test_visual_tier_still_screen_gets_visual_recheck_backstop():
    """持续静止超过 VISUAL_RECHECK_S：即使没有任何事件也兜底刷新一次视觉，
    防止上下文长期过期（读书翻页恰好像素差不足等漏报不至于无限延续）。"""
    kw = dict(_VW_BASE)
    kw["now"] = kw["last_visual_turn"] + brain.VISUAL_RECHECK_S
    assert brain.turn_wants_visual(**kw) is True


def test_visual_tier_constants_keep_perception_faster_than_image():
    """心跳（重新判断/文本轮）必须明显密于视觉兜底：高频的是感知，不是带图。"""
    assert brain.HEARTBEAT_S < brain.VISUAL_RECHECK_S
    assert brain.VISUAL_RECHECK_S >= 600


def test_step_observation_is_none_for_text_only_turn():
    """run() 必须真的把无图轮的 observation 传成 None（而不是只算了个标志位）。"""
    src = _src(BRAIN)
    assert "observation=session.observe(vis) if visual_wanted else None" in src


def test_backend_strips_all_images_from_text_only_turn():
    """无图轮不只是省新截图：上一轮留在上下文里的图、工具结果里 history/inspect
    拉回的图都必须占位，否则图像 token 照样花出去。"""
    backend = brain.VisualDirectBackend({})
    backend.history = [
        {"role": "user", "content": [
            {"type": "text", "text": "CURRENT source_id=old"},
            {"type": "image", "source": {"type": "base64", "data": "AAA"}}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "history"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": [
            {"type": "text", "text": "回看结果"},
            {"type": "image", "source": {"type": "base64", "data": "BBB"}}]}]},
    ]
    backend.turn_without_visual = True
    messages = backend._messages()
    blocks = [b for m in messages for b in m["content"]]
    tool_blocks = [b for m in messages for b in m["content"]
                   if b.get("type") == "tool_result"]
    assert not [b for b in blocks if b.get("type") == "image"], "无图轮上下文里不允许残留任何图像块"
    assert all(not any(i.get("type") == "image" for i in b.get("content", []))
               for b in tool_blocks), "工具结果里的旧图也必须被过滤"

    backend.turn_without_visual = False
    messages = backend._messages()
    assert any(b.get("type") == "image" for m in messages for b in m["content"]), \
        "标志清除后图像必须恢复，不能把带图轮也搞成无图"


# ---------------------------------- companion 重启重放窗口收窄到气泡生命（d）

def _place_offer(tmp_path, monkeypatch, offer: dict) -> None:
    monkeypatch.setattr(live, "DIR", tmp_path)
    (tmp_path / "offer.json").write_text(json.dumps(offer), encoding="utf-8")


def test_companion_replay_window_tracks_bubble_lifetime():
    """重放窗口 = 气泡生命（30~90s）+ 一次重启宽限，随句长伸缩，且有硬上限。"""
    short = live.companion_max_age_s({"text": "在"})
    long = live.companion_max_age_s({"text": "很" * 600})
    assert long > short
    assert short >= live.BUBBLE_READ_S
    assert long <= live.BUBBLE_MAX_S + live.COMPANION_REPLAY_GRACE_S
    # 旧值 900s 彻底没了：最长的句子也不允许 15 分钟后复活
    assert long < 120


def test_fresh_companion_survives_a_normal_gui_restart(tmp_path, monkeypatch):
    """正常热更新/崩溃拉起只花几秒：当句不能丢。"""
    _place_offer(tmp_path, monkeypatch,
                 {"id": "c1", "kind": "companion", "text": "还在忙呀。", "t": time.time() - 3})
    offer = live.read_offer()
    assert offer and offer["id"] == "c1"


def test_bubble_expired_companion_is_not_replayed(tmp_path, monkeypatch):
    """气泡生命 + 宽限一过，GUI 重启不许把旧句重新弹出来。"""
    text = "这是一句不长不短正好用来算气泡寿命的陪伴语。"
    age = live.companion_max_age_s({"text": text}) + 5
    _place_offer(tmp_path, monkeypatch,
                 {"id": "c2", "kind": "companion", "text": text, "t": time.time() - age})
    assert live.read_offer() is None


def test_fifteen_minute_old_companion_never_resurfaces(tmp_path, monkeypatch):
    """旧行为的直接回归：900s 前的 companion 句在任何句子长度下都必须过期。"""
    _place_offer(tmp_path, monkeypatch,
                 {"id": "c3", "kind": "companion", "text": "x", "t": time.time() - 900})
    assert live.read_offer() is None


def test_action_offer_replay_window_is_unchanged(tmp_path, monkeypatch):
    """动作 offer 的 180s 短窗口不动——本次只收窄 companion，不扩范围。"""
    _place_offer(tmp_path, monkeypatch,
                 {"id": "o1", "kind": "offer", "text": "要我清一下 C 盘吗？",
                  "options": ["好的", "不用"], "t": time.time() - 170})
    assert live.read_offer() is not None
    _place_offer(tmp_path, monkeypatch,
                 {"id": "o2", "kind": "offer", "text": "要我清一下 C 盘吗？",
                  "options": ["好的", "不用"], "t": time.time() - 190})
    assert live.read_offer() is None


# --------------------------- 240 心跳 / 300 超时的背靠背边角（e）

def test_no_back_to_back_turn_after_a_timeout_long_turn():
    """一轮跑到 TURN_TIMEOUT_S=300（>HEARTBEAT_S=240）后，轮末时间戳一刷，
    下一个 tick 不允许立刻满足心跳。"""
    turn_start = 10_000.0
    turn_end = turn_start + brain.TURN_TIMEOUT_S
    assert brain.heartbeat_is_due(turn_end + 2, turn_end) is False
    # 从轮末起再等满一个心跳间隔，才允许下一轮
    assert brain.heartbeat_is_due(turn_end + brain.HEARTBEAT_S, turn_end) is True


def test_run_loop_refreshes_last_turn_after_a_turn_finishes():
    """run() 必须在 backend.run 返回后再写一次 last_turn（不只在轮首写）。"""
    src = inspect.getsource(brain.run)
    run_call = src.index("backend.run(")
    assert "last_turn = time.time()" in src[run_call:], \
        "轮末不刷新 last_turn，超时轮结束后背靠背立刻再开一轮"


# ------------------------------------------------------ 监督容错（f，零覆盖补齐）

class _AliveProc:
    def poll(self):
        return None


class _DeadProc:
    def __init__(self, code=1):
        self._code = code

    def poll(self):
        return self._code


def test_log_swallows_oserror_and_keeps_counting(monkeypatch):
    """磁盘满（ENOSPC）时 log() 不许上抛——它曾穿过 finally 带走全部子进程。"""

    class NoSpaceLog:
        def open(self, *a, **k):
            raise OSError("no space left on device")

    class NoSpaceDir:
        def mkdir(self, *a, **k):
            raise OSError("no space left on device")

    monkeypatch.setattr(live, "SUP_LOG", NoSpaceLog())
    monkeypatch.setattr(live, "DIR", NoSpaceDir())
    monkeypatch.setattr(live, "_LOG_FAILS", 0)
    assert live.log("磁盘满也要活着，日志只是附属品") is None
    assert live._LOG_FAILS == 1


def test_reconcile_drops_child_after_max_consecutive_start_failures():
    """单孩子连续 MAX_START_FAILS 次拉不起来：摘除它，其余孩子继续。

    start 全程注入、抛 OSError，不真的拉起/杀任何进程。
    """
    attempts: list[str] = []

    def boom(name):
        attempts.append(name)
        raise OSError("handle exhausted")

    procs = {"brain": _DeadProc(), "gui": _AliveProc(), "recorder": _AliveProc()}
    fails: dict = {}
    dropped: dict = {}
    logs: list[str] = []
    drop_clock = 10_000.0
    for _ in range(live.MAX_START_FAILS):
        live.reconcile_exits(procs, fails, start=boom, log=logs.append,
                             spawned={}, dropped=dropped, now=drop_clock)

    assert "brain" not in procs, "连续起不来的孩子必须被摘出快速轮询"
    assert set(procs) == {"gui", "recorder"}, "摘除不能牵连健康的孩子"
    assert fails["brain"] == live.MAX_START_FAILS
    assert len(attempts) == live.MAX_START_FAILS
    assert any("放弃" in m for m in logs), "摘除要在监督日志里留一句"
    assert "brain" in dropped, "摘除不是永久删除：必须进慢速探活表"

    # 摘除后进慢速探活：间隔未到（60s）不许立刻重试，不刷 CPU
    live.reconcile_exits(procs, fails, start=boom, log=logs.append,
                         spawned={}, dropped=dropped, now=drop_clock)
    assert len(attempts) == live.MAX_START_FAILS


def test_reconcile_leaves_living_children_untouched():
    """活着的孩子绝不重启。"""
    started: list[str] = []
    procs = {"gui": _AliveProc()}
    live.reconcile_exits(procs, {}, start=lambda n: started.append(n) or _DeadProc(),
                         log=lambda m: None)
    assert started == []


def test_successful_restart_resets_failure_counter():
    """失败几次后成功一次：计数清零，孩子留在监督表里。"""
    revived = _AliveProc()
    state = {"left": 2}

    def flaky(name):
        if state["left"]:
            state["left"] -= 1
            raise OSError("transient")
        return revived

    procs = {"gui": _DeadProc()}
    fails: dict = {}
    live.reconcile_exits(procs, fails, start=flaky, log=lambda m: None)
    live.reconcile_exits(procs, fails, start=flaky, log=lambda m: None)
    assert fails == {"gui": 2}
    live.reconcile_exits(procs, fails, start=flaky, log=lambda m: None)
    assert fails == {"gui": 0}
    assert procs["gui"] is revived


# ---------------- P1-1：Popen 成功但秒退必须计入启动失败 ----------------

def test_successful_start_with_immediate_exit_is_counted_as_failure():
    """热更新写入语法错误 brain 的真实路径：start 不抛异常，但新 proc 每个
    tick（2s）都已退出。审查者实证旧代码 60 轮 spawn 60 次、fails 恒 0、
    永不摘除；新代码必须在连续秒退达 MAX_START_FAILS 时把它转入慢速探活。
    """
    spawned_procs: list = []

    def start(name):
        proc = _DeadProc(1)
        spawned_procs.append(proc)
        return proc

    t0 = 5_000.0
    procs = {"brain": _DeadProc(1)}
    spawned_at = {"brain": t0}
    fails: dict = {}
    dropped: dict = {}
    logs: list[str] = []
    for i in range(live.MAX_START_FAILS - 1):
        live.reconcile_exits(procs, fails, start=start, log=logs.append,
                             spawned=spawned_at, dropped=dropped, now=t0 + 2 * i)
    assert fails["brain"] == live.MAX_START_FAILS - 1
    assert "brain" in procs and not dropped, "预算未满前继续快速重试"
    assert len(spawned_procs) == live.MAX_START_FAILS - 1

    live.reconcile_exits(procs, fails, start=start, log=logs.append,
                         spawned=spawned_at, dropped=dropped,
                         now=t0 + 2 * (live.MAX_START_FAILS - 1))
    assert "brain" not in procs, "连续秒退达上限必须摘出快速轮询"
    assert "brain" in dropped, "摘除后进慢速探活，不是永久删除"
    assert fails["brain"] == live.MAX_START_FAILS
    assert len(spawned_procs) == live.MAX_START_FAILS
    assert any("秒退" in m for m in logs)


def test_child_that_survived_window_then_exited_restarts_without_failure():
    """活过观察窗之后的退出（正常热更新/手动重启后的意外退出）：计 0、
    立刻重新拉起，不进慢速探活。"""
    t0 = 7_000.0
    revived = _AliveProc()
    procs = {"gui": _DeadProc(0)}
    spawned_at = {"gui": t0 - live.SPAWN_OBSERVE_S - 1}
    fails = {"gui": 4}
    dropped: dict = {}
    live.reconcile_exits(procs, fails, start=lambda n: revived, log=lambda m: None,
                         spawned=spawned_at, dropped=dropped, now=t0)
    assert procs["gui"] is revived
    assert fails["gui"] == 0
    assert dropped == {}


def test_start_success_is_not_trusted_until_window_survived():
    """start 成功本身不再清零：新 proc 活过观察窗才确认健康。

    防的是「秒退 proc 靠下一次 start 没抛异常洗白计数」的旧 bug 变体。
    """
    t0 = 9_000.0
    fresh = _AliveProc()
    procs = {"recorder": _DeadProc(1)}
    spawned_at = {"recorder": t0 - 2}
    fails = {"recorder": 2}
    dropped: dict = {}
    args = dict(start=lambda n: fresh, spawned=spawned_at, dropped=dropped)

    live.reconcile_exits(procs, fails, log=lambda m: None, now=t0, **args)
    assert procs["recorder"] is fresh
    assert fails["recorder"] == 3, "旧 proc 秒退要计数，新 proc 还在观察期"

    def no_restart(name):
        raise AssertionError("活着的孩子不该被重启")

    live.reconcile_exits(procs, fails, start=no_restart, log=lambda m: None,
                         spawned=spawned_at, dropped=dropped, now=t0 + 3)
    assert fails["recorder"] == 3, "观察窗内只是观察期，不能清零"

    live.reconcile_exits(procs, fails, start=no_restart, log=lambda m: None,
                         spawned=spawned_at, dropped=dropped,
                         now=t0 + live.SPAWN_OBSERVE_S + 1)
    assert fails["recorder"] == 0
    assert dropped == {}


# ---------------- P1-2：摘除后的慢速探活与复活 ----------------

@pytest.mark.parametrize("name", ["brain", "gui", "recorder"])
def test_dropped_child_revives_after_successful_slow_probe(name):
    """摘除 → 未到探活时刻不动 → 探活拉起（观察期内仍摘除）→ 活过观察窗
    恢复正常轮询。brain/gui/recorder 三者行为必须一致。"""
    t0 = 20_000.0
    stable = _AliveProc()
    calls: list = []

    def start(n):
        assert n == name
        calls.append(1)
        return stable

    dropped = {name: {"retry_at": t0, "proc": None, "spawned": None}}
    procs: dict = {}
    spawned_at: dict = {}
    fails = {name: live.MAX_START_FAILS}
    logs: list[str] = []
    kw = dict(start=start, log=logs.append, spawned=spawned_at, dropped=dropped)

    live.reconcile_exits(procs, fails, now=t0 - 1, **kw)
    assert calls == [] and procs == {}

    live.reconcile_exits(procs, fails, now=t0, **kw)
    assert len(calls) == 1 and name not in procs
    assert dropped[name]["proc"] is stable, "探活 proc 在观察期内挂在 dropped 上"

    live.reconcile_exits(procs, fails, now=t0 + live.SPAWN_OBSERVE_S - 1, **kw)
    assert name not in procs and name in dropped and len(calls) == 1

    live.reconcile_exits(procs, fails, now=t0 + live.SPAWN_OBSERVE_S + 1, **kw)
    assert procs.get(name) is stable
    assert name not in dropped
    assert fails[name] == 0
    assert any("恢复" in m for m in logs), "恢复必须记监督日志"

    live.reconcile_exits(procs, fails, now=t0 + 600, **kw)
    assert len(calls) == 1, "恢复后走正常轮询，不许重复 spawn"


def test_dropped_child_keeps_waiting_silently_after_failed_probes():
    """探活 proc 秒退 / start 抛 OSError：静默等待下一个探活周期，不刷日志；
    直到某次探活活过观察窗才复活。"""
    t0 = 30_000.0
    mode = {"kind": "dead"}
    stable = _AliveProc()

    def start(n):
        if mode["kind"] == "oserror":
            raise OSError("disk still full")
        if mode["kind"] == "dead":
            return _DeadProc(1)
        return stable

    dropped = {"brain": {"retry_at": t0, "proc": None, "spawned": None}}
    procs: dict = {}
    spawned_at: dict = {}
    fails = {"brain": live.MAX_START_FAILS}
    logs: list[str] = []
    kw = dict(start=start, log=logs.append, spawned=spawned_at, dropped=dropped)

    # 第一次探活拉起秒退 proc：观察窗内被判定失败，回等待，零日志
    live.reconcile_exits(procs, fails, now=t0, **kw)
    live.reconcile_exits(procs, fails, now=t0 + 2, **kw)
    assert procs == {} and logs == []
    assert dropped["brain"]["proc"] is None
    assert dropped["brain"]["retry_at"] == t0 + 2 + live.RESPAWN_PROBE_S

    # 下一轮探活 start OSError：继续静默等待
    mode["kind"] = "oserror"
    live.reconcile_exits(procs, fails, now=t0 + 2 + live.RESPAWN_PROBE_S, **kw)
    assert procs == {} and logs == []
    assert dropped["brain"]["retry_at"] == t0 + 2 + 2 * live.RESPAWN_PROBE_S

    # 磁盘恢复：探活拉起成功
    mode["kind"] = "ok"
    revive_t = t0 + 2 + 2 * live.RESPAWN_PROBE_S
    live.reconcile_exits(procs, fails, now=revive_t, **kw)
    assert dropped["brain"]["proc"] is stable and procs == {} and logs == []
    live.reconcile_exits(procs, fails, now=revive_t + live.SPAWN_OBSERVE_S + 1, **kw)
    assert procs.get("brain") is stable and "brain" not in dropped
    assert fails["brain"] == 0
    assert len([m for m in logs if "恢复" in m]) == 1


# ---------------- R2-1：秒退第 30 次刚拉起的 proc 不许被 retire 遗弃 ----------------

class _TrackedProc:
    """带 terminate 计数、可切换存活的假 proc：用来核对「跟踪或被 terminate」二态。"""

    def __init__(self, *, alive: bool):
        self.alive = alive
        self.terminated = 0

    def poll(self):
        return None if self.alive else 1

    def terminate(self):
        self.terminated += 1


def _run_30_early_exit_ticks(start, *, t0=40_000.0):
    """连跑 30 个 2s tick：旧 proc 每个 tick 都在观察窗内秒退。"""
    procs = {"brain": _DeadProc(1)}
    spawned_at = {"brain": t0}
    fails: dict = {}
    dropped: dict = {}
    logs: list[str] = []
    for i in range(live.MAX_START_FAILS):
        live.reconcile_exits(procs, fails, start=start, log=logs.append,
                             spawned=spawned_at, dropped=dropped, now=t0 + 2 * i)
    t30 = t0 + 2 * (live.MAX_START_FAILS - 1)
    return procs, spawned_at, fails, dropped, logs, t30


def test_30th_early_exit_spawn_surviving_is_adopted_by_probe_and_revives():
    """故障恰在第 30 次判定的 tick 边界恢复：第 30 次 start 返回的是活 proc。

    旧代码先 ``procs[name]=new`` 再 ``retire()``（pop procs + dropped.proc=None），
    new 既不在 procs 也不在 dropped、从未 terminate；60s 后探活再拉第二个，
    恢复后两个活实例只有一个被跟踪（brain 双开=两个自主模型会话）。
    新代码：new 挂为在飞探活 proc，活过观察窗即由探活逻辑复活，全程只有一个
    活实例且它始终被跟踪——不存在第三态。
    """
    spawned_procs: list[_TrackedProc] = []

    def start(name):
        # 前 29 次秒退，第 30 次故障恢复、返回活 proc
        proc = _TrackedProc(alive=(len(spawned_procs) == live.MAX_START_FAILS - 1))
        spawned_procs.append(proc)
        return proc

    procs, spawned_at, fails, dropped, logs, t30 = _run_30_early_exit_ticks(start)
    thirtieth = spawned_procs[-1]

    assert fails["brain"] == live.MAX_START_FAILS
    assert "brain" not in procs, "达上限仍要摘出快速轮询"
    assert dropped["brain"]["proc"] is thirtieth, "刚拉起的活 proc 必须被 dropped 在飞槽位接管"
    assert dropped["brain"]["spawned"] == t30
    assert thirtieth.terminated == 0, "活着的 proc 不该被 terminate，它还要被探活观察"

    kw = dict(start=start, log=logs.append, spawned=spawned_at, dropped=dropped)

    # 观察窗内：不允许再 spawn（否则就是双开），也不能提前复活
    live.reconcile_exits(procs, fails, now=t30 + 2, **kw)
    assert len(spawned_procs) == live.MAX_START_FAILS
    assert "brain" not in procs and dropped["brain"]["proc"] is thirtieth

    # 活过观察窗：探活确认复活，回到正常轮询——不必再等 60s
    live.reconcile_exits(procs, fails, now=t30 + live.SPAWN_OBSERVE_S + 1, **kw)
    assert procs.get("brain") is thirtieth
    assert "brain" not in dropped
    assert fails["brain"] == 0
    assert any("恢复" in m for m in logs)

    # 恢复后长期运行：同一实例、零额外 spawn、零 terminate
    live.reconcile_exits(procs, fails, now=t30 + 600, **kw)
    assert len(spawned_procs) == live.MAX_START_FAILS
    alive_procs = [p for p in spawned_procs if p.alive]
    assert len(alive_procs) == 1 and alive_procs[0] is thirtieth
    tracked = list(procs.values()) + [e["proc"] for e in dropped.values()
                                      if e.get("proc") is not None]
    assert thirtieth in tracked and thirtieth.terminated == 0, "不存在孤儿"


def test_30th_early_exit_spawn_that_dies_too_keeps_silent_probe_cycle():
    """第 30 次 start 返回的 proc 也秒退：它作为在飞探活 proc 留观，下一 tick
    被判定探活失败后回等待、继续 60s 探活周期（静默不刷日志），直到磁盘恢复、
    某次探活活过观察窗才复活。"""
    spawned_procs: list[_TrackedProc] = []
    mode = {"kind": "dead"}
    stable = _TrackedProc(alive=True)

    def start(name):
        proc = stable if mode["kind"] == "ok" else _TrackedProc(alive=False)
        spawned_procs.append(proc)
        return proc

    procs, spawned_at, fails, dropped, logs, t30 = _run_30_early_exit_ticks(start)
    thirtieth = spawned_procs[-1]
    assert dropped["brain"]["proc"] is thirtieth, "即使也秒退，new 也要先挂在飞槽位而不是丢弃"
    assert dropped["brain"]["spawned"] == t30
    assert len([m for m in logs if "放弃" in m]) == 1
    n_logs_at_retire = len(logs)

    kw = dict(start=start, log=logs.append, spawned=spawned_at, dropped=dropped)

    # 下一 tick：在飞探活秒退（age=2 < 观察窗）→ 回等待，静默、无新 spawn
    live.reconcile_exits(procs, fails, now=t30 + 2, **kw)
    assert procs == {}
    assert dropped["brain"]["proc"] is None
    assert dropped["brain"]["spawned"] is None
    assert dropped["brain"]["retry_at"] == t30 + 2 + live.RESPAWN_PROBE_S
    assert len(spawned_procs) == live.MAX_START_FAILS
    assert len(logs) == n_logs_at_retire, "退休之后的探活失败必须零日志"

    # 未到探活时刻：不重试
    live.reconcile_exits(procs, fails, now=t30 + 2 + live.RESPAWN_PROBE_S - 1, **kw)
    assert len(spawned_procs) == live.MAX_START_FAILS

    # 到点再探一次，仍秒退 → 继续等待一个周期，依然静默
    probe_t = t30 + 2 + live.RESPAWN_PROBE_S
    live.reconcile_exits(procs, fails, now=probe_t, **kw)
    assert dropped["brain"]["proc"] is spawned_procs[-1]
    live.reconcile_exits(procs, fails, now=probe_t + 2, **kw)
    assert dropped["brain"]["proc"] is None
    assert dropped["brain"]["retry_at"] == probe_t + 2 + live.RESPAWN_PROBE_S
    assert len(logs) == n_logs_at_retire

    # 磁盘恢复：探活活过观察窗后复活，无孤儿
    mode["kind"] = "ok"
    revive_t = probe_t + 2 + live.RESPAWN_PROBE_S
    live.reconcile_exits(procs, fails, now=revive_t, **kw)
    assert dropped["brain"]["proc"] is stable and procs == {}
    live.reconcile_exits(procs, fails, now=revive_t + live.SPAWN_OBSERVE_S + 1, **kw)
    assert procs.get("brain") is stable and "brain" not in dropped
    assert fails["brain"] == 0
    assert stable.terminated == 0
    assert len([p for p in spawned_procs if p.alive]) == 1


# ---------------- P2-3：监督日志写盘恢复可见 ----------------

def test_log_reports_recovery_and_resets_counter(monkeypatch):
    """写盘失败→成功跳变时补一条恢复日志并归零（pythonw 无控制台时唯一证据）。"""

    class FakeHandle:
        def __init__(self, sink):
            self.sink = sink

        def write(self, data):
            self.sink.append(data)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    written: list[str] = []

    class FailOnceLog:
        def __init__(self):
            self.calls = 0

        def open(self, *a, **k):
            self.calls += 1
            if self.calls == 1:
                raise OSError("no space left on device")
            return FakeHandle(written)

    class OkDir:
        def mkdir(self, *a, **k):
            pass

    monkeypatch.setattr(live, "SUP_LOG", FailOnceLog())
    monkeypatch.setattr(live, "DIR", OkDir())
    monkeypatch.setattr(live, "_LOG_FAILS", 0)

    live.log("写不进去的一行")
    assert live._LOG_FAILS == 1
    live.log("恢复后的一行")
    assert live._LOG_FAILS == 0
    joined = "".join(written)
    assert "恢复" in joined and "1 次失败" in joined


# ---------------- P2-4：启动期单个孩子失败不击穿监督进程 ----------------

def test_startup_failure_of_one_child_does_not_abort_the_rest():
    """0 字节磁盘/句柄耗尽时，{n: start(n)} 在 try 外曾让监督进程直接
    traceback、一个孩子都没有。"""

    def start(name):
        if name == "recorder":
            raise OSError("no space")
        return _AliveProc()

    procs, spawned_at, fails, dropped = live.spawn_children(
        ["brain", "gui", "recorder"], start=start, log=lambda m: None, now=1.0)
    assert set(procs) == {"brain", "gui"}
    assert set(spawned_at) == {"brain", "gui"}
    assert fails["recorder"] == 1
    assert dropped["recorder"]["retry_at"] == 0.0, "第一轮 reconcile 就立刻再试一次"
    assert dropped["recorder"]["proc"] is None


# ---------------- P2-1/P2-2：away lead 分流 + 心跳调用点 kwarg 钉死 ----------------

def test_away_heartbeat_lead_does_not_encourage_opening_a_window():
    """10-13 晚反馈后心跳不再是开口许可证：away lead 不打扰；非 away 的无图
    lead 也必须明说「时间到了不是开口理由」，任何 lead 都不得再鼓励自然开口。"""
    tree = ast.parse(_src(BRAIN))
    run_fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "run")
    leads = []
    for node in ast.walk(run_fn):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "lead" for t in node.targets)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            leads.append(node.value.value)
    away_leads = [s for s in leads if "别打扰" in s]
    assert len(away_leads) == 1, "away 分支必须有自己的不打扰 lead"
    assert "自然开口" not in away_leads[0]
    assert not any("自然开口" in s for s in leads), \
        "10-13 反馈后任何心跳 lead 都不得再写「自然开口窗口」"
    assert any("时间到了不是开口理由" in s for s in leads), \
        "无图心跳 lead 必须明写时间不是开口理由"
    # 分流条件必须真挂在 watching 的 away 阈值上，不能是写了却进不去的死分支
    assert 'away = idle_s >= watching.DEFAULTS["away_s"]' in _src(BRAIN)


def test_run_heartbeat_note_call_kwargs_match_signature():
    """调用点关键字写错一个，run() 每轮 TypeError、brain 起不来，而纯函数
    测试全绿（PR #16 复审 P2-2）。AST 钉死调用 kwarg 集合 == 签名 kw-only 形参。
    """
    tree = ast.parse(_src(BRAIN))
    sig_fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "heartbeat_note_if_due")
    expected = {a.arg for a in sig_fn.args.kwonlyargs}
    run_fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "run")
    calls = [n for n in ast.walk(run_fn)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "heartbeat_note_if_due"]
    assert len(calls) == 1
    call = calls[0]
    assert call.args == [], "必须全关键字调用，错一个名字就每轮 TypeError"
    assert {kw.arg for kw in call.keywords} == expected
