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


def test_heartbeat_turn_is_not_instructed_to_default_to_quiet():
    """这是本次最关键的一条：心跳缩短了，但提示词仍说「默认安静」的话，
    等于每 4 分钟主动锁死自己一次，修复自我抵消。

    提示词已抽成纯函数 brain.heartbeat_note()——直接测实际下发的文本，
    不再从 run() 的 AST 里捞（捞 AST 会把「本来就该安静」的背景准备分支
    一起卷进来，旧 helper 必须小心绕开两层陷阱）。
    """
    prompt = brain.heartbeat_note(240)
    assert "默认安静" not in prompt, \
        "心跳轮还在要求默认安静——屏幕静止时它就是唯一触发源，会把精灵锁死"
    assert "不需要先取证" in prompt or "不取证" in prompt, \
        "心跳轮必须点明：自然开口不需要先取证，否则模型只会去找理由"
    assert "时间在走" in prompt, "心跳轮要给出「屏幕没动不等于没事发生」的判据"


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
              fb="", return_due=False, continue_due=False, goal_due=False)
    kw.update(over)
    return kw


def test_heartbeat_window_opens_on_a_plain_quiet_heartbeat():
    """人在、无回话义务、无锚点的心跳轮：自然开口窗口提示成立。"""
    note = brain.heartbeat_note_if_due(**_hb_kw())
    assert note and "兜底心跳轮" in note


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
    logs: list[str] = []
    for _ in range(live.MAX_START_FAILS):
        live.reconcile_exits(procs, fails, start=boom, log=logs.append)

    assert "brain" not in procs, "连续起不来的孩子必须被摘出监督表"
    assert set(procs) == {"gui", "recorder"}, "摘除不能牵连健康的孩子"
    assert fails["brain"] == live.MAX_START_FAILS
    assert len(attempts) == live.MAX_START_FAILS
    assert any("放弃" in m for m in logs), "摘除要在监督日志里留一句"

    # 摘除后不再每 2 秒重试它（不刷 CPU）
    live.reconcile_exits(procs, fails, start=boom, log=logs.append)
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
