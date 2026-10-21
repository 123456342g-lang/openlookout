"""小精灵的大脑：一个长期运行的 VISTA 会话。
- 同一个模型会话持续存在；VISTA 保存每一帧原始画面（视觉记忆），模型可history / inspect 回看。
- 每次屏幕有明显变化，就以 STEP 轮次喂给同一个会话；模型用companion 工具决定“说话/提议/安静”。
- GUIDE.md（对用户的长期理解）跨重启保留在 sprite_home/companion/GUIDE.md。用户的反馈（好的/不用/纠正）以文字追加进下一轮，只作为权衡依据，不是命令。
- 上下文快满时，VISTA 自己交接，不重开会话；进程崩溃才重启：python -m vista.benchmarks.desktop.brain
"""
from __future__ import annotations

import json, math, os, shutil, threading, time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import certifi

from sprite.config import sprite_home
from sprite.i18n import LiveText
from sprite.proactive.chat import build_request, normalize_response, strip_images
from sprite.proactive.control import paused, quit_requested
from sprite.proactive.first_run import provider_problem
from sprite.proactive.provider import bootstrap_dotenv, load_provider

from . import coach, desktopfacts, memory, systemfacts, watching
from .decision_engine import DecisionEngine
from .agenda import Agenda
from .stale_guard import action_key, note_stale_block, note_stale_success

HOME = sprite_home()
COMPANION = HOME / "companion"
GUIDE = COMPANION / "GUIDE.md"
WORKING = COMPANION / "WORKING.md"
PERCEIVE = HOME / "perceive"
FEEDBACK = PERCEIVE / "feedback.jsonl"
OFFERS = PERCEIVE / "offers.jsonl"
PROJECT = Path(__file__).resolve().parents[3]
CHANGE_MIN = 0.01          # 屏幕缩略图平均差异超 1% 就重新判断
MIN_GAP_S = 5              # 页面切换后尽快跟上；节流交给模型判断和输出闸
# 心跳不再单独叫醒模型。静止且没有任何触发时，调用次数应接近零。
# HEARTBEAT_S 只给「已经由别的触发打开的轮」标注距上一轮过了多久。
HEARTBEAT_S = 240
# 带图模型轮是最贵的资源。高频感知由 2s 本地哨兵免费完成（缩略图 diff、
# 窗口切换、键鼠 idle、操作流断点、C盘/内存）；只有强视觉信号才把新截图
# 送进模型，纯心跳/维护/续办轮走无图文本轮（VISTA 核心支持 STEP 空
# observation：runtime.prepare_input STEP observation=None → 空 bundle，
# 历史画面仍在视觉记忆里）。屏幕持续静止时，带图轮靠这个兜底间隔保底。
VISUAL_RECHECK_S = 900
PREP_EVERY_TURNS = 24      # rotate one background refresh window every N turns,
                           # even during a busy screen
# An unanswered user message is the one trigger the sprite cannot afford to
# miss.  Measured on 10-13: a message written at 07:09:09 waited for the turn
# already in flight and the bubble appeared at 07:10:02 -- 52.8s, of which the
# reply turn itself was a fraction.  The turn loop only woke on behaviour
# triggers (screen change, timing, maintenance), none of which fire just
# because someone is waiting for an answer, so a quiet screen could strand a
# message until the next unrelated event.
#
# So: never let an unanswered message go unanswered for longer than this.  It
# is a ceiling, not a target -- the loop still runs as often as its own
# triggers allow, and MIN_GAP_S still throttles.
#
# The ceiling cannot be "forever".  An old unanswered message is no longer
# someone waiting (they may have walked away, or answered elsewhere), and
# re-arming on it forever would manufacture turns out of a stale transcript.
REPLY_DEADLINE_S = 90
PENDING_MAX_AGE_S = 1800
# A companion turn is a glance at the screen plus a short talk, not a research
# project.  The claude runner defaults to 3600s per turn, which let one turn
# outlive the entire conversation -- the sprite simply said nothing for hours
# while the model kept probing.  Five minutes is long enough to read a page and
# check two leads, short enough that a wrong turn gets cut off.
#
# The first turn pays for rebuilding the whole visual context, so it needs more
# headroom than a steady-state step.  Measured: the first turn burned 11 tool
# calls on setup before it had anything to say, and a 240s cap truncated it
# before it ever reached the companion call -- the decision was recorded, the
# bubble never appeared.
TURN_TIMEOUT_S = int(os.environ.get("OPENLOOKOUT_TURN_TIMEOUT_S") or 300)
# The decision lease is the runner's "the model should have committed a decision
# by now" watchdog.  It defaults to 7200s, which is longer than the silence it
# is supposed to prevent -- so a turn that forgets to call companion is never
# interrupted and the sprite just goes quiet.  Give it the same order of
# magnitude as the turn budget: past this, a silent turn is a failure worth
# cutting off rather than waiting out.
DECISION_LEASE_S = int(os.environ.get("OPENLOOKOUT_DECISION_LEASE_S")
                       or TURN_TIMEOUT_S)
# Optional override. The model id itself comes from provider.json at build time.
# Empty means "use the provider file"; do not substitute a personal model name.
ACTIVE_MODEL = str(os.environ.get("OPENLOOKOUT_MODEL") or "")
# How many HTTP calls one turn may make. The old loop did 13, each carrying
# the full screenshot. 4 is the cap unless OPENLOOKOUT_MAX_CALLS says otherwise.
def model_call_budget(env=None) -> int:
    env = os.environ if env is None else env
    raw = str(env.get("OPENLOOKOUT_MAX_CALLS") or "4").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, min(value, 8))


def thumb(visual) -> list[int]:
    import io
    from PIL import Image
    return list(Image.open(io.BytesIO(visual.data)).convert("L").resize((48, 30)).getdata())


def changed(a, b) -> bool:
    """Meaningful thumbnail change. A missing baseline is not a change."""
    if not a or not b:
        return False
    return sum(abs(x - y) for x, y in zip(a, b)) / (len(a) * 255) >= CHANGE_MIN


def model_turn_due(
    *,
    screen_due: bool = False,
    window_due: bool = False,
    background_due: bool = False,
    maintenance_due: bool = False,
    timing_due: bool = False,
    feedback: str = "",
    return_due: bool = False,
    continue_due: bool = False,
    goal_due: bool = False,
    reply_due: bool = False,
) -> bool:
    """True only when this moment should call the model.

    A still screen, the heartbeat timer, and the mere existence of history
    files are not triggers. Those facts can still be attached to a turn that
    something else already opened.
    """
    return bool(
        screen_due or window_due or background_due or maintenance_due
        or timing_due or feedback or return_due or continue_due
        or goal_due or reply_due
    )


@dataclass(frozen=True)
class ScreenSample:
    revision: int
    visual: object
    thumbnail: list[int]
    window: tuple[str, str]
    captured_at: float
    feedback_at: float


class LiveScreen:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._latest = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def sample(self) -> ScreenSample:
        from .session import screen_visual

        visual = screen_visual()
        thumbnail = thumb(visual)
        foreground = watching.foreground()
        window = (foreground.get("proc", ""), foreground.get("title", ""))
        feedback_at = FEEDBACK.stat().st_mtime if FEEDBACK.exists() else 0.0
        with self._lock:
            previous = self._latest
            updated = (previous is None or changed(previous.thumbnail, thumbnail)
                       or previous.window != window or feedback_at != previous.feedback_at)
            revision = (previous.revision if previous else 0) + int(updated)
            if updated:
                self._latest = ScreenSample(revision, visual, thumbnail, window, time.time(), feedback_at)
            return self._latest

    def latest(self) -> ScreenSample:
        with self._lock:
            return self._latest

    def start(self) -> None:
        self.sample()
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.wait(2):
            try:
                self.sample()
            except Exception as exc:
                print(f"[brain] screen sample failed: {type(exc).__name__}", flush=True)


def _rows(path: Path) -> list[dict]:
    if not path.exists(): return []
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try: out.append(json.loads(raw))
        except ValueError: pass
    return out


OPS = PERCEIVE / "operations.jsonl"
RESIDUAL_CACHE: dict = {"at": 0.0, "text": ""}


def _tail_jsonl(path: Path, window_bytes: int = 400_000) -> list[dict]:
    """读记录器正在写的文件：共享读 + 容忍被截断的半行；任何失败都返回空表，不影响大脑〡。"""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - window_bytes))
            data = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    for raw in data.splitlines():
        if not raw.startswith("{"):
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _event_time(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


TIMING_CACHE: dict = {"at": 0.0, "events": []}
TIMING_TRACKER = None


def ops_events(*, refresh_s: float = 5.0, now: float | None = None) -> list[dict]:
    """行为事件流（供时机算法使用）。5 秒内复用，失败时返回上一份快照。"""
    now = now or time.time()
    if now - TIMING_CACHE["at"] < refresh_s and TIMING_CACHE["events"]:
        return TIMING_CACHE["events"]
    events: list[dict] = []
    try:
        from sprite.proactive import timing as _tm
        events = _tm.normalize(_tail_jsonl(OPS))
    except Exception as exc:
        print(f"[brain] timing events 不可用：{exc!r}", flush=True)
    if events:
        TIMING_CACHE["at"] = now
        TIMING_CACHE["events"] = events
    return TIMING_CACHE["events"]


def timing_tracker():
    """惰性创建时机追踪器；导入失败就化成 None（大脑照常跑，只是回到旧的心跳触发）。

    timing v2：时效按「我们第一次看见这条事件的时刻」算，而不是它自称发生的时刻。
    记录器把 focus 区间写在结束时却用开始时刻做 ts，不这样改，一个刚刚才可行动的边界会被算成过期。
    """
    global TIMING_TRACKER
    if TIMING_TRACKER is None:
        try:
            from sprite.proactive.timing import Tracker as _T
            TIMING_TRACKER = _T()
        except Exception as exc:
            print(f"[brain] timing 不可用，回到心跳触发：{exc!r}", flush=True)
            TIMING_TRACKER = False
    return TIMING_TRACKER or None


def residual_fact(*, window_min: float = 90.0, refresh_s: float = 5.0, now: float | None = None) -> str:
    """【此刻的异常，s_t】：本地可复算的注意力信号，只看本机行为流水，不读屏、不调用模型。

    s_t = -log2 P(应用_t | 应用_(t-1)) - log2 P(类型_t)，一阶马尔可夫 + 0.5 平滑。
    预期模型由同一段流水现场学出，所以 P 有版本可复算，不是模型在线自由裁量。
    s_t 高：本机平时不这样；s_t 低：一切照常。这是注意力信号，不替模型决定开不开口。
    """
    now = now or time.time()
    if now - RESIDUAL_CACHE["at"] < refresh_s and RESIDUAL_CACHE["text"]:
        return RESIDUAL_CACHE["text"]
    events, app = [], "?"
    for row in _tail_jsonl(OPS):
        moment = _event_time(row.get("ts"))
        if moment is None or moment > now + 5:
            continue
        kind = str(row.get("type") or "?")
        named = str(row.get("app") or "").strip()
        if named:
            app = named
        events.append({"t": moment, "app": app, "type": kind,
                       "title": str(row.get("title") or "")[:36]})
    window = [event for event in events if now - event["t"] <= window_min * 60]
    if len(window) < 40:
        RESIDUAL_CACHE.update(at=now, text="")
        return ""
    trans: dict[str, dict[str, int]] = {}
    types: dict[str, int] = {}
    for previous, current in zip(window, window[1:]):
        row = trans.setdefault(previous["app"], {})
        row[current["app"]] = row.get(current["app"], 0) + 1
        types[current["type"]] = types.get(current["type"], 0) + 1
    apps = {event["app"] for event in window}
    scored = []
    for previous, current in zip(window, window[1:]):
        counts = trans.get(previous["app"], {})
        p_app = (counts.get(current["app"], 0) + 0.5) / (sum(counts.values()) + 0.5 * (len(apps) + 1))
        p_type = (types.get(current["type"], 0) + 0.5) / (sum(types.values()) + 0.5 * (len(types) + 1))
        scored.append(dict(current, s=-math.log2(p_app) - math.log2(p_type)))
    latest = scored[-1]
    interesting = []
    for event in sorted(scored, key=lambda item: -item["s"]):
        if event["s"] < 7 or now - event["t"] > 45 * 60:
            continue
        if any(event["app"] == kept["app"] and event["type"] == kept["type"] for kept in interesting):
            continue
        interesting.append(event)
        if len(interesting) == 3:
            break
    since = min((now - event["t"] for event in scored if event["s"] >= 7), default=None)
    lines = [f"【此刻的异常 s_t】本地可复算：s_t = -log2 P(应用|上一应用) - log2 P(类型)。"
             f"预期模型由本机最近 {int(window_min)} 分钟、{len(window)} 条行为流水现场学出（不是模型猜的）。",
             f"当前 s_t={latest['s']:.2f}｜{latest['app']}｜{latest['type']}"
             + (f"{latest['title']}" if latest["title"] else "")]
    if interesting:
        lines.append("最近 45 分钟里不寻常的时刻（越高越不像本机平时的样子）。")
        for event in interesting:
            stamp = time.strftime("%H:%M:%S", time.localtime(event["t"]))
            lines.append(f"- {stamp} s_t={event['s']:.2f}｜{event['app']}｜{event['type']}"
                         + (f"｜{event['title']}" if event["title"] else ""))
    if since is not None:
        lines.append(f"距上次明显异常约 {since / 60:.0f} 分钟。")
    lines.append("s_t 只是统计信号，不是结论：s_t 高说明此刻得看一眼是否与用户当下目标有关。"
                 "s_t 低不能排除重复劳动未解决目标或自然交流机会，仍需结合语义证据判断。不要为了指标开口，也不要把分数念给用户。")
    text = "\n".join(lines)
    previous_s = RESIDUAL_CACHE.get("logged_s")
    if now - RESIDUAL_CACHE.get("logged_at", 0.0) >= 20 or previous_s is None or abs(latest["s"] - previous_s) >= 2.0:
        try:
            with (PERCEIVE / "residual.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({
                    "t": round(latest["t"], 1), "s": round(latest["s"], 2),
                    "app": latest["app"], "type": latest["type"], "events": len(window),
                    "top": [{"t": round(event["t"], 1), "s": round(event["s"], 2),
                             "app": event["app"], "type": event["type"]} for event in interesting]},
                    ensure_ascii=False) + "\n")
            RESIDUAL_CACHE["logged_at"] = now
            RESIDUAL_CACHE["logged_s"] = latest["s"]
        except OSError:
            pass
    RESIDUAL_CACHE.update(at=now, text=text)
    print(f"[brain] residual s_t={latest['s']:.2f} app={latest['app']} type={latest['type']} "
          f"events={len(window)} top={len(interesting)}", flush=True)
    return text


HISTORY_LOG = Path(os.environ.get("OPENLOOKOUT_EVENTS") or (HOME / "events.jsonl"))
LONG_TERM_CACHE: dict = {"at": 0.0, "text": ""}

_NOISE_SEG = ("wxwork", "tencent files", "code cache", "service worker", "cachestorage",
              "cefcache", "leveldb", "gpucache", "crashpad", "cache", "logs", "log",
              "node_modules", ".git", "__pycache__", "appdata", "temp", "tmp",
              "shadercache", "dawncache", "grshadercache")
_NOISE_NAME = {"log", "log.old", "temp-index", "the-real-index", "index", "lock",
               "config.cfg", "kv.db", "kv.db-wal", "kv.db-shm", "preferences",
               "local state", "history", "history-journal"}
_DOC_EXT = {".md", ".txt", ".doc", ".docx", ".pdf", ".xls", ".xlsx", ".csv", ".ppt",
            ".pptx", ".py", ".js", ".ts", ".json", ".exe", ".zip", ".msi", ".7z",
            ".rar", ".png", ".jpg", ".jpeg", ".html", ".yml", ".yaml", ".toml",
            ".cfg", ".ini", ".bat", ".ps1", ".sh", ".sql", ".ipynb"}


def _is_user_file(path: str) -> bool:
    """排除应用内部缓存/日志（WXWork / CEF cache、leveldb、kv.db-wal 之类）。

    这些是「文件事件」里最大的假阳性来源，混进来会把应用自己的写入当成用户的工作。
    """
    if not path:
        return False
    low = path.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    if name in _NOISE_NAME:
        return False
    if any(seg in low for seg in _NOISE_SEG):
        return False
    if "." not in name:
        return False
    return ("." + name.rsplit(".", 1)[-1]) in _DOC_EXT


def long_term_fact(*, days: float = 7.0, refresh_s: float = 600.0,
                   now: float | None = None) -> str:
    """【长期模式：从整机操作历史（不是小精灵自己那 90 秒窗口）里连续感知。"
    这是「持续主动感知的记忆那一半：只看本机流水、本地可复算、不读屏、不调模型。
    给出最近几天的时间去向与反复改动的文件——它们是判断「用户现在在做什么」
    「卡在哪」「不值得帮」的强锚点，每 refresh_s 秒重算一次。    """
    now = now or time.time()
    if now - LONG_TERM_CACHE["at"] < refresh_s and LONG_TERM_CACHE["text"]:
        return LONG_TERM_CACHE["text"]
    rows = _tail_jsonl(HISTORY_LOG, window_bytes=6_000_000)
    if len(rows) < 200:
        LONG_TERM_CACHE.update(at=now, text="")
        return ""
    cutoff = now - days * 86400.0
    app_s: dict[str, float] = {}
    app_n: dict[str, int] = {}
    touched: dict[str, set] = {}
    count: dict[str, int] = {}
    kept = 0
    prev_app = "?"
    for row in rows:
        moment = _event_time(row.get("ts"))
        if moment is None or moment < cutoff or moment > now + 300:
            continue
        kind = str(row.get("type") or "?")
        named = str(row.get("app") or "").strip()
        if kind == "focus" and named:
            prev_app = named
        app = named or prev_app
        kept += 1
        app_n[app] = app_n.get(app, 0) + 1
        try:
            dur = float(row.get("dur_s") or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        app_s[app] = app_s.get(app, 0.0) + (dur if dur > 0 else 15.0)
        path = str(row.get("path") or "").strip()
        if kind in ("file_save", "file_open", "file_create") and _is_user_file(path):
            low = path.replace("\\", "/")
            count[low] = count.get(low, 0) + 1
            touched.setdefault(low, set()).add(kind)
    if kept < 200:
        LONG_TERM_CACHE.update(at=now, text="")
        return ""
    top_apps = sorted(app_n.items(), key=lambda item: -item[1])[:5]
    churn = [(path, n) for path, n in count.items() if n >= 3]
    churn.sort(key=lambda item: -item[1])
    lines = [f"【长期模式】整机操作历史（不是小精灵自己的窗口）：最近 {days:.0f} 天读了 {kept} 条行为事件。",
             "时间去向：" + "、".join(f"{app} {n} 次" for app, n in top_apps)]
    if churn:
        lines.append("反复读写的文件（长期在手，是判断当下目标的最好锚点）。")
        for path, n in churn[:6]:
            lines.append(f"- {path} {n} 次")
    lines.append("用法：如果当前画面与上面某个文件/应用对得上，说明用户此刻在做这件事的延续。"
                 "可以据此提前把下一步准备好（做完再说，不要问要不要做）。"
                 "但长期模式不构成打扰理由—是否开口仍由当下时机决定，宁可 quiet。")
    text = "\n".join(lines)
    LONG_TERM_CACHE.update(at=now, text=text)
    print(f"[brain] long-term days={days:.0f} events={kept} churn={len(churn)}", flush=True)
    return text


def idle_scan_fact(*, heartbeat: bool, idle_s: float, now: float) -> str:
    """Invite a goal-driven preparation decision without selecting a topic."""
    if not heartbeat:
        return ""
    if idle_s >= watching.DEFAULTS["away_s"]:
        mode = "键鼠长时间未动：可能在阅读或等待，也可能暂离，结合连续画面判断，不把无操作直接当成人已离开。"
    else:
        mode = "结合连续画面判断当前节奏：可以准备下一步，也可以自然接话；本轮并不要求开口。"
    return (f"【背景准备】{mode} 把操作记录发现问题、后台维护和自然交流放进同一个判断："
            "先看是否有用户尚未解决的问题，再决定补证据、推进帮助、维护、聊天或安静；"
            "自己选择最值得继续的一步，不按固定主题轮转。"
            "quiet 只决定是否开口，不代表后台停止；未知资料可能值得一次小查询，真实必须等待才标waiting。"
            "不要一次性扫完整历史，沿具体假设逐步补证据；比较继续原方案、换方向、准备下一步和等待的收益，"
            "把预期改善、验证方式与结果写进 WORKING.md，不是为了有事可做而制造任务。"
            "基础服务和公共检索只在能改变当前判断或改善交流时使用，不自动查每日天气。")


def heartbeat_is_due(now: float, last_turn_finished: float) -> bool:
    """距上一轮**结束**是否已过 HEARTBEAT_S。

    关键约定：run() 不只在开轮时刷 ``last_turn``，轮末还会再刷一次。
    一轮可以跑到 TURN_TIMEOUT_S=300s，而 HEARTBEAT_S=240s < 300s；若时间戳
    只记轮首，超时轮结束的下一个 tick 立刻满足心跳条件，背靠背再开一轮
    （issue #11 验收：240/300 边角）。以轮末为基准，心跳间隔才真的是 240s。
    """
    return now - last_turn_finished >= HEARTBEAT_S


def feedback_needs_visual(text: str | None) -> bool:
    """用户这句反馈是否**指向眼前画面**（不附图就答不准）。

    10-14 实测：他打字回话时，旧逻辑无条件把这一轮升级成带图视觉轮，截图 +
    视觉编码是回话延迟的主要成本。但「帮我清理下 C 盘」「周报怎么写」
    「别再提清理了」这类纯文本意图根本不需要新画面，watching/systemfacts 的
    文本事实已够判断——这些走无图快速轮（issue #27）。只有「这个窗口」
    「上面那段」「屏幕白屏了」这类视觉指代才附图。词表宁可略宽：误判只是
    多花一轮图钱，漏判会让模型无图瞎答、回话反而更慢；无图轮模型仍可在
    调查中用 ``_refresh_screen`` 同轮补图，这只是首拍省不省的区别。
    """
    if not text:
        return False
    lowered = text.lower()
    return any(word in lowered for word in VISUAL_CUE_WORDS)


# 视觉指代词表：命中任一即认为他在说自己正看着的东西。「这/那」故意保留
# 单字——「这个怎么弄」「那样不行」绝大多数都需要看屏。
VISUAL_CUE_WORDS = (
    "这", "那", "此", "屏幕", "画面", "窗口", "弹窗", "对话框",
    "白屏", "黑屏", "花屏", "显示", "看到", "看见", "上面",
    "左上角", "左下角", "右上角", "右下角", "按钮", "图标", "颜色",
    "this", "that", "screen", "window",
)


def turn_wants_visual(
    *,
    screen_due: bool,
    window_due: bool,
    timing_due: bool,
    fb: str,
    return_due: bool,
    reply_due: bool,
    now: float,
    last_visual_turn: float,
    visual_recheck_s: float = VISUAL_RECHECK_S,
    reply_text: str | None = None,
) -> bool:
    """本轮是否需要把**新截图**送进模型（带图轮 = 最贵的资源）。

    高频感知由 2s 本地哨兵免费完成；模型轮分两级：强视觉信号（屏幕内容
    变化、窗口切换、操作流断点、**指向眼前画面的**用户开口、离开回来、
    回话临期）才附图；纯心跳、后台维护、历史小页、续办、目标轮，以及
    **纯文本反馈**（feedback_needs_visual 判否：清理 C 盘、写周报这类
    不看屏也能答的话）走无图文本轮——watching 的计时事实（同屏停多久、
    卡没卡、窗口轨迹）是纯文本，足以支撑「此刻该不该说话」的判断，屏幕
    没新内容时再送一遍图只是重复花钱。

    新文字消息本身仍负责**唤醒**循环（主闸门里的 ``fb`` 不动，2s 内开轮）；
    这里只决定它附不附图。``reply_pending`` 不进这里——它不是唤醒触发
    （循环闸门只认 reply_due），刚发消息后的心跳轮用文本回话即可。

    无图轮不是闭嘴轮：模型仍可依据文本事实说话或续办，只是开口必须有
    时间以外的具体事由（见 heartbeat_note）。静止超过
    ``visual_recheck_s`` 兜底刷新一次，防止视觉上下文长期过期。
    """
    if screen_due or window_due or timing_due or return_due:
        return True
    if reply_due:
        # 临期回话默认仍附图（调用方没带原文时）。带了原文就只在这句话
        # 指向眼前画面时附图，纯文本回话不强制视觉轮（issue #27）。
        if reply_text is None:
            return True
        return feedback_needs_visual(reply_text)
    # 只有指向眼前画面的反馈才附图（issue #27）；纯文本反馈照样立即开轮，
    # 只是省掉截图与视觉编码——唤醒在主循环闸门，不在这里。
    if fb and feedback_needs_visual(fb):
        return True
    return (now - last_visual_turn) >= visual_recheck_s


def heartbeat_note(turn_gap_s: float) -> str:
    """无图心跳轮专用提示词（实际下发给模型的那段）。

    心跳让模型**重新核对**时间事实与后台状态，不是开口许可证。10-13 晚
    实测：旧文案写「不需要先取证也能说的日常短话此刻就成立」，心跳轮随即
    产出「九点多……今天这一天挺长的」——时间到了不构成事由（#10 定稿：
    事由驱动，不是时间驱动），既打扰又白烧 token。

    心跳轮不送新截图（turn_wants_visual 为 False 时 observation=None），
    所以文案同时禁止回看历史画面：需要看现场就 quiet，等下一个带图轮。
    但仍不许写「默认安静」——watching 事实可能真的报了「卡住/来回翻」，
    那种文本事由成立时它应该说话。

    数字语义（issue #11 新发现 3）：``turn_gap_s`` 必须是**距上一轮判断真实
    经过的时间**（run() 在重置 last_turn 之前捕获的 now-last_turn），不能拿
    键鼠无输入时长 ``idle_s`` 顶替——idle 量的是「人有没有碰键鼠」，看视频、
    读书、用另一台设备都会让它变大，但那不等于「距上次判断」。
    """
    gap_min = max(0.0, turn_gap_s) / 60.0
    return (
        f"\n【这是兜底心跳轮，距上一轮判断已 {gap_min:.0f} 分钟，期间没有新的行为事件，本轮也没有新画面】"
        "只重新核对时间事实（同一屏停多久、卡没卡、人在不在）与后台状态。"
        "时间到了本身不是开口理由：开口必须有具体事由——他刚做的事、"
        "已核实且此刻对他有用的结果、或对他手头那件事的一个真实想法。"
        "单纯感慨时间、天色、辛苦（「这个点了」「今天挺长的」「入夜了」）"
        "是填充不是内容，一律 quiet。"
        "本轮不要回看历史画面；需要看现场才能判断就 quiet，等下一个有画面的轮次。"
        "但计时事实若真的报了「卡住 / 来回翻 / 刚完成一个阶段」，"
        "那是成立的事由，可以就这件具体事说一句。"
    )


def heartbeat_note_if_due(*, heartbeat_due: bool, turn_gap_s: float, idle_s: float,
                          reply_pending: bool, fb: str, return_due: bool,
                          continue_due: bool, goal_due: bool,
                          has_visual: bool = True) -> str:
    """无图心跳轮的专用提示；不该附时返回空串。

    明确排除：

    - ``reply_pending``：他在等回话，【优先回话】已经在本轮提示里，心跳鼓励
      叠加上去会让「必须回」和「可以自然开口」两套指令互相打架；
    - 人离开了（键鼠无输入达 ``watching.DEFAULTS['away_s']``，300s）：同一轮
      的 watching 事实附的是「别打扰，回来再说」，这里若鼓励开口就是正面
      冲突，必须让位——away 心跳轮回落到后面的「默认安静」分支；
    - 有真实锚点的轮次（新反馈 fb / away 回归 return_due / 续办 / 目标）：
      它们各有自己的提示词，心跳文案不叠加；
    - ``has_visual``：带图心跳（900s 视觉兜底轮）有新 CURRENT 可看，走正常
      带图轮提示；心跳文案明说「本轮没有新画面」，附图时附它就是说谎。
    """
    if not heartbeat_due:
        return ""
    # 注意：保持独立 if，不要把 reply_pending 并进布尔或表达式——
    # test_wakeup_stays_bounded_to_the_deadline 全文件扫描该变量后接 or 的
    # 写法，那只允许出现在唤醒闸门语义里。
    if reply_pending:
        return ""
    if has_visual:
        return ""
    if fb or return_due or continue_due or goal_due:
        return ""
    if idle_s >= watching.DEFAULTS["away_s"]:
        return ""
    return heartbeat_note(turn_gap_s)


def conversation_fact(*, idle_s: float, now: float) -> str:
    """Bring delivered dialogue into the same VISTA judgment as the screen."""
    from sprite.proactive import conversation

    rows = conversation.history(limit=24)
    pending = conversation.pending_message(rows)
    latest_user = max((index for index, row in enumerate(rows) if row.get("role") == "user"), default=-1)
    transcript = []
    relevant_start = max(0, latest_user - 1) if latest_user >= 0 else max(0, len(rows) - 2)
    for index, row in enumerate(rows):
        if index < relevant_start:
            continue
        if row.get("kind") == "reply":
            continue
        role = "你" if row.get("role") == "user" else "我"
        stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(float(row.get("t", 0) or 0)))
        transcript.append(f"{stamp} {role}：{str(row.get('text') or '')[:500]}")

    # 精灵自己刚说过什么。少了这一段，模型每轮都在重新发现同一件事，
    # 于是把同一条结论换个说法再讲一遍——用户看到的就是"一直说重复的事"。
    # kind=reply 是回话轮的附带产物（常见的是占位式敷衍），不算"说过的话"：
    # 把它列出来等于提醒模型去重复它。
    recent_own = [
        str(row.get("text") or "").strip()
        for row in rows
        if row.get("role") == "assistant" and row.get("kind") != "reply"
        and str(row.get("text") or "").strip()
    ][-6:]
    if recent_own:
        said = "；".join(line.replace("\n", " ")[:80] for line in recent_own)
        own_recent = ("【我最近说过的话】" + said +
                      "\n这几条你已经讲过了。没有新的回应或新证据就不要换个说法重讲；"
                      "也别把没得到回应的枝节自动续下去。")
    else:
        own_recent = "【我最近说过的话】还没有，这是第一次开口。"

    latest_assistant = max((index for index, row in enumerate(rows) if row.get("role") == "assistant"), default=-1)
    replied = any(row.get("role") == "user" for row in rows[latest_assistant + 1:])
    response_context = (
        "最近开口后尚未收到他的接话；没有回应不等于拒绝，也不证明他对你引入的枝节感兴趣，别自动续讲调查结果。"
        if latest_assistant >= 0 and not replied else
        "结合他实际回应的内容理解兴趣与分歧，不把你的提问当成他已经认可的话题。"
    )
    turn_context = (
        f"【待回应话轮 id={conversation.message_id(pending)}】他{pending.get('text', '')}\n"
        "这是对你说的话，先接住这个意思，companion.reply_to 填这个 id。已有依据足够就直接回答。"
        "不要为了回答普通聊天先做全量扫描、读整份笔记或检索；当前页面变了不等于这句对话失效。"
        if pending else
        "【当前没有待回应话轮】旧问题只用于理解，不反复补答。不要接着自己的未获回应观点续讲，"
        "也不要把屏幕里的修复汇报当成给你的新消息。"
    )
    return (
        f"【对话现场】出现于 {time.strftime('%H:%M:%S', time.localtime(now))}。"
        f"键鼠静止 {idle_s:.0f} 秒，这是节奏线索，不是聊天开关，也不证明他离开。\n"
        "仅附最近的真实交流，旧事不当当前事实。工作进行中也可以聊。\n"
        + own_recent + "\n" + turn_context + "\n" + response_context + "\n"
        + ("\n".join(transcript) if transcript else "你们还没有实际对话，可结合画面自然开一个话题。")
    )


def pending_reply_age(now: float) -> float | None:
    """Seconds since the user wrote something the sprite has not answered yet.

    Returns ``None`` when nothing is pending, or when the pending message is too
    old to still mean "he is waiting".  Age (not a deadline) is the primitive
    the turn loop needs: it decides both whether this turn should be a reply
    turn and how much of the reply budget is left.

    The transcript is the source of truth here, not feedback.jsonl: a message
    typed into the dialog lands in both, but only conversation.jsonl records
    that the sprite actually answered (``reply_to``).
    """
    try:
        from sprite.proactive import conversation
        pending = conversation.pending_message(conversation.history(limit=24))
    except Exception:
        return None
    if pending is None:
        return None
    try:
        age = now - float(pending.get("t", 0) or 0)
    except (TypeError, ValueError):
        return None
    if age < 0 or age > PENDING_MAX_AGE_S:
        return None
    return age


def pending_reply_text(now: float) -> str:
    """The unanswered user line, or "" when nothing is still waiting."""
    if pending_reply_age(now) is None:
        return ""
    try:
        from sprite.proactive import conversation
        pending = conversation.pending_message(conversation.history(limit=24))
    except Exception:
        return ""
    if not isinstance(pending, dict):
        return ""
    return str(pending.get("text") or "")


def pending_reply_deadline(now: float) -> float | None:
    """Epoch seconds by which an unanswered user message must be replied to."""
    age = pending_reply_age(now)
    if age is None:
        return None
    return now + max(0.0, REPLY_DEADLINE_S - age)


def new_feedback(since: float) -> str:
    """自上次以来用户说过的话和对提议的回应，交给模型权衡（不是命令）。"""
    lines = [f"- 用户反馈（{r.get('kind', 'outcome')}）：{r['text']}" for r in _rows(FEEDBACK) if r.get("t", 0) > since]
    lines += [f"- 用户对你的提议“{r.get('text', '')}”的回应：{r['result']}"
              for r in _rows(OFFERS) if r.get("result") in ("accepted", "dismissed") and r.get("t_answer", 0) > since]
    if not lines: return ""
    return ("用户刚刚对你说了话：先理解他是在正常聊天、提问还是反馈，不把普通问题当成改进意见。"
            "用标签是本地粗分类，可能有误，以原文和对话为准。反馈用于校准判断，不能当作执行授权或忽略真实问题。\n"
            + "\n".join(lines))


def watching_fact(watcher, thumb, idle_s: float | None = None) -> str:
    """这一屏停了多久、有没有在推进、是不是在来回折腾。人走了就返回空串。

    idle_s 供测试注入；不传则取真实键鼠空闲秒数。
    """
    try:
        sig = watching.foreground()
        idle = watching.idle_seconds() if idle_s is None else idle_s
        state = watcher.observe(thumb, sig.get("title", ""), idle_s=idle,
                                proc=sig.get("proc", ""))
        # Tests and degraded capture paths may pass no frame; without a frame
        # a foreground title is not enough evidence to emit a trail.
        facts = [state.line(), watcher.activity_line if thumb is not None else "",
                 watcher.pattern_line if thumb is not None else ""]
        return "\n".join(x for x in facts if x)
    except Exception:
        return ""


def system_fact(sysw) -> str:
    """视觉看不见的那部分：C 盘内存占资源的进程正常就空串，绝不多嘴。"""
    try:
        return sysw.observe().line()
    except Exception:
        return ""


class MaintenanceSignal:
    def __init__(self, watcher):
        self.watcher = watcher
        self.checked_at = None
        self.signature = None
        self.line = ""
        self.pending = False
        self.facts = None

    def observe(self, now: float, *, refresh: bool = False) -> str:
        if not refresh and self.checked_at is not None and now - self.checked_at < 30:
            return self.line
        try:
            facts = self.watcher.observe(now)
            self.facts = facts
            line = facts.line()
            signature = (
                facts.disk_critical,
                facts.disk.get("free_gb") if facts.disk.get("ok") else None,
                facts.mem_critical,
                facts.mem.get("avail_gb") if facts.mem.get("ok") else None,
                bool(line),
            )
        except Exception:
            return ""
        if signature != self.signature:
            self.pending = self.pending or bool(line)
        if not line:
            self.pending = False
        self.checked_at, self.signature, self.line = now, signature, line
        return line

    def consume(self) -> None:
        self.pending = False


def memory_fact() -> str:
    """他最近接受过或拒绝过什么。短到没有成本，但能防止换个说法再提一遍。"""
    try:
        return memory.brief(HOME)
    except Exception:
        return ""


class ModelRateLimited(RuntimeError):
    """The provider answered 429. Stop this turn; do not spin."""


# Two sleeps, three HTTP tries, then give up. Not an open-ended 60-retry.
RATE_LIMIT_BACKOFF_S = (2.0, 8.0)
RATE_LIMIT_COOLDOWN_S = 600.0
RATE_LIMIT_SAY = LiveText("rate_limit")


def model_response(request, *, sleep=time.sleep):
    import http.client
    import ssl
    import urllib.error
    import urllib.request

    transport_attempt = 0
    rate_attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            if getattr(error, "code", None) != 429:
                raise
            if rate_attempt >= len(RATE_LIMIT_BACKOFF_S):
                raise ModelRateLimited("模型服务暂时限流，本轮不再重试。") from error
            sleep(RATE_LIMIT_BACKOFF_S[rate_attempt])
            rate_attempt += 1
            print(f"[brain] model rate-limited; backoff {RATE_LIMIT_BACKOFF_S[rate_attempt - 1]}s "
                  f"({rate_attempt}/{len(RATE_LIMIT_BACKOFF_S)})", flush=True)
        except urllib.error.URLError as error:
            if transport_attempt or not isinstance(error.reason, (ssl.SSLEOFError, ConnectionResetError)):
                raise
            transport_attempt += 1
            print(f"[brain] model transport interrupted: {type(error.reason).__name__}; retrying request once", flush=True)
        except http.client.RemoteDisconnected:
            if transport_attempt:
                raise
            transport_attempt += 1
            print("[brain] model transport interrupted: RemoteDisconnected; retrying request once", flush=True)


def post_model(cfg: dict, body: dict):
    """Send one model turn and return an Anthropic-shaped payload plus the request."""
    protocol = str(cfg.get("protocol") or "anthropic")
    request = build_request(cfg, body)
    payload = model_response(request)
    return normalize_response(protocol, payload), request


def arm_rate_limit(backend, now: float | None = None) -> None:
    """Pause model turns and say so once, in plain language."""
    now = time.time() if now is None else now
    backend.rate_limited_until = now + RATE_LIMIT_COOLDOWN_S
    if getattr(backend, "rate_limit_said", False):
        return
    backend.rate_limit_said = True
    PERCEIVE.mkdir(parents=True, exist_ok=True)
    say = str(RATE_LIMIT_SAY)
    row = {
        "t": now,
        "kind": "companion",
        "say": say,
        "speech": {"kind": "companion", "say": say},
        "activity": "",
        "state": "",
        "source": "vista",
    }
    temporary = PERCEIVE / "current.json.tmp"
    try:
        temporary.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        temporary.replace(PERCEIVE / "current.json")
    except OSError:
        return
    try:
        from sprite.proactive.help import publish
        publish({"id": f"rate-{time.time_ns()}", "t": now, "text": say,
                 "topic": "陪伴", "kind": "companion"})
    except Exception:
        return


class DirectReply:
    """对齐容器后端的回包形状（brain 只读这几个字段）。"""

    def __init__(self, text: str = "", returncode: int = 0, boundary: str | None = "turn",
                 *, rate_limited: bool = False):
        self.final_message = text
        self.returncode = returncode
        self.boundary = boundary
        self.rate_limited = rate_limited


class _LegacyDirectBackend:
    """不走容器，直接调模型的传输。

    每轮是一次独立请求，按 provider.json 的协议走 Anthropic messages 或 OpenAI
    chat/completions。帧按顺序喂进去，模型仍然能看到刚刚发生了什么。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.session = None
        self.history: list[dict] = []

    def attach(self, session) -> None:
        self.session = session

    def run(self, task_input) -> DirectReply:
        prompt = _extract_text(task_input)
        if not prompt:
            return DirectReply("")
        msgs = self.history[-8:] + [{"role": "user", "content": prompt}]
        body = {"model": self.cfg["model"], "max_tokens": 2048, "messages": msgs}
        try:
            req = build_request(self.cfg, body)
            d = normalize_response(self.cfg.get("protocol") or "anthropic", model_response(req))
        except Exception as e:
            print(f"[brain] 模型调用失败：{type(e).__name__}", flush=True)
            return DirectReply("")
        text = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text").strip()
        if text:
            self.history.append({"role": "assistant", "content": text})
        return DirectReply(text)


def _extract_text(task_input) -> str:
    """从 VISTA 准备好的输入里取出本轮的公开文字（拿不到就返回空）。"""
    for attr in ("public_text", "text", "prompt"):
        v = getattr(task_input, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    return str(task_input)[:2000] if task_input else ""


class LocalClaudeTextBackend:
    """Host Claude Code transport without Docker or MCP.

    Claude is asked for one JSON companion decision per turn.  This deliberately
    uses only stdin/stdout; no MCP config, bridge, or container is created.
    """
    def __init__(self, cfg: dict, runtime=None):
        self.cfg, self.runtime, self.session = cfg, runtime, None
        self.mode = "host-local-no-mcp"
        self.binary = os.environ.get("OPENLOOKOUT_CLAUDE_BIN") or shutil.which("claude") or "claude"
        self._tool_server = None

    def attach(self, session) -> None:
        self.session = session
        self.history: list[dict] = []
        self._tool_id = 0

    def run(self, task_input):
        import subprocess
        from vista.core.profiles import Phase
        if self.runtime is None or self.session is None:
            return DirectReply("", returncode=1, boundary=None)
        self.runtime.begin_turn(task_input)
        prompt = _extract_text(task_input)
        images = task_input.observation.images()
        tools = self.runtime.tools()
        prompt += "\nVISTA local tools (call through Claude Code's host Bash using the command below; " \
                  "the call is dispatched into VISTA TaskRuntime, with its normal schemas and checks):\n"
        prompt += json.dumps(tools, ensure_ascii=False)
        prompt += ("\nCall a VISTA tool with: python -m vista.benchmarks.desktop.local_tool TOOL_NAME 'JSON_ARGUMENTS'. "
                   "The command returns the actual tool result. Use this for desktop/history/basic services and "
                   "call companion exactly once at the end. Claude Code native Bash/Read/etc are also available "
                   "on the host. This turn includes actual screen image blocks; inspect them directly.")
        env = os.environ.copy()
        model = str(self.cfg.get("model") or os.environ.get("OPENLOOKOUT_MODEL") or "").strip()
        if model:
            env["ANTHROPIC_MODEL"] = model
        cmd = [self.binary, "-p", "--output-format", "stream-json",
               "--input-format", "stream-json",
               "--setting-sources", "user", "--no-chrome"]
        if model:
            cmd[2:2] = ["--model", model]
        try:
            if self._tool_server is None:
                from .local_tool import LocalToolServer
                self._tool_server = LocalToolServer(self.runtime)
                self._tool_server.start()
            content = [{"type": "text", "text": prompt}]
            for image in images:
                content.append({"type": "image", "source": {"type": "base64", "media_type": image["mime_type"], "data": image["data"]}})
            if self.history:
                content.insert(0, {"type": "text", "text": "Prior VISTA conversation:\\n" + json.dumps(self.history[-12:], ensure_ascii=False)})
            message = {"type": "user", "message": {"role": "user", "content": content}}
            env["OPENLOOKOUT_LOCAL_TOOL_ENDPOINT"] = self._tool_server.endpoint
            env["OPENLOOKOUT_LOCAL_TOOL_TOKEN"] = self._tool_server.token
            proc = subprocess.run(cmd, input=json.dumps(message, ensure_ascii=False) + "\n", capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", env=env,
                                  cwd=str(PROJECT), timeout=240)
            raw = (proc.stdout or "").strip()
            if proc.returncode:
                print(f"[brain] local Claude exited {proc.returncode}", flush=True)
                return DirectReply(raw, returncode=proc.returncode, boundary=None)
            outputs=[]
            for line in raw.splitlines():
                try: event=json.loads(line)
                except ValueError: continue
                if event.get("type") == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "text": outputs.append(block.get("text", ""))
                elif event.get("type") == "result":
                    outputs.append(str(event.get("result", "")))
            text_out="\n".join(x for x in outputs if x).strip()
            self.history.append({"role":"user","text":prompt[:12000]})
            self.history.append({"role":"assistant","text":text_out[:4000]})
            return DirectReply(text_out)
        except Exception as exc:
            print(f"[brain] local Claude failed: {type(exc).__name__}", flush=True)
            return DirectReply("", returncode=1, boundary=None)


class VisualDirectBackend:
    """Direct HTTP backend. Speaks provider.json's anthropic or openai protocol."""

    def __init__(self, cfg: dict, runtime=None):
        self.cfg = cfg
        self.runtime = runtime
        # This backend is an explicit compatibility path, never a sandbox.
        # Keep the marker available to logs/tests/UI so a transport failure
        # cannot be mistaken for the Docker Claude backend.
        self.mode = "direct"
        self.session = None
        self.history: list[dict] = []
        self.turn_starts: list[int] = []
        self.history_context = ""
        self.opportunity_probe_context = None
        self.live_screen = None
        self.screen_revision = 0
        self.screen_sample = None
        self.feedback_since = time.time()
        self.max_segments = max(0, model_call_budget() - 1)
        self.max_readonly_segments = 3
        # True = 本轮不送新截图（无图心跳/维护轮）：_messages 把历史图像也
        # 全部占位，防止「新图省了、上一轮那张图还在」继续花图像 token。
        # _refresh_screen 在调查中收到新画面时清除（那一刻起本轮恢复带图）。
        self.turn_without_visual = False
        self.stale_state: dict = {}
        self.rate_limited_until = 0.0
        self.rate_limit_said = False

    def attach(self, session) -> None:
        self.session = session

    def _append_input(self, task_input, *, scene_update: bool = False) -> None:
        content = []
        presented = self.runtime.present_input(task_input)
        visuals = [visual for observation in task_input.observation.displayed_observations
                   for visual in observation.views]
        for index, image in enumerate(task_input.observation.images()):
            if index < len(presented.image_labels):
                content.append({"type": "text", "text": presented.image_labels[index]})
            content.append({"type": "text", "text":
                "CURRENT source_id=" + visuals[index].source_id})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": image["mime_type"], "data": image["data"]}})
        public_text = _extract_text(task_input)
        # Keep the model's interaction policy adjacent to each fresh visual
        # observation.  This prevents ordinary refreshes from degenerating
        # into activity/status broadcasts while still permitting relevant
        # evidence-backed conversation or a concrete reversible offer.
        if scene_update or not public_text:
            public_text += ("\n[Interaction guidance] This is not a status broadcast. "
                            "Use the CURRENT visual and recent operations to understand the user's work. "
                            "Evidence-backed conversation is allowed when relevant; offer a concrete reversible action only when tools can help. "
                            "Otherwise choose quiet. Do not invent weather, generic activity reports, or unrelated topics.")
        agenda = getattr(self.session or self.runtime.session, "agenda", None)
        if agenda is not None:
            execution_context = agenda.context()
            if public_text.endswith(execution_context):
                public_text = public_text[:-len(execution_context)].rstrip()
        content.append({"type": "text", "text": public_text})
        if not scene_update:
            self.turn_starts.append(len(self.history))
        self.history.append({"role": "user", "content": content})

    def _refresh_screen(self) -> bool:
        if self.live_screen is None or self.session is None:
            return False
        sample = self.live_screen.latest()
        if sample.revision <= self.screen_revision:
            return False
        from vista.core.profiles import Phase

        now = time.time()
        feedback = new_feedback(self.feedback_since)
        self.feedback_since = now
        text = ("【现场更新】调查期间画面或用户消息发生了变化。这是新的 CURRENT，旧观察仍由 VISTA history 保留。"
                "先判断目标是否延续、旧问题是否仍在；保留有用成果，暂停已经不相关的调查，重新比较下一步。"
                "不能直接发布或执行基于旧现场的决定。\n" + feedback + "\n"
                + conversation_fact(idle_s=watching.idle_seconds(), now=now))
        task_input = self.runtime.prepare_input(Phase.STEP, public_text=text,
                                                observation=self.session.observe(sample.visual))
        self.runtime.begin_turn(task_input)
        self._append_input(task_input, scene_update=True)
        self.screen_revision = sample.revision
        self.screen_sample = sample
        # 新现场已经进上下文：本轮从无图轮升级为带图轮，_messages 不得再
        # 把这张图占位掉（否则模型收到「现场更新」却看不到更新了什么）。
        self.turn_without_visual = False
        return True

    def _messages(self) -> list[dict]:
        starts = self.turn_starts or [index for index, message in enumerate(self.history)
                                     if message["role"] == "user"
                                     and all(block.get("type") != "tool_result" for block in message["content"])]
        start = starts[-2] if len(starts) >= 2 else (starts[-1] if starts else 0)
        active_start = self.turn_starts[-1] if self.turn_starts else len(self.history)
        start = max(start, min(active_start, len(self.history) - 16))
        messages = self.history[start:]
        while messages and messages[0]["role"] == "user" and any(
                block.get("type") == "tool_result" for block in messages[0]["content"]):
            messages.pop(0)
        # 无图轮（turn_without_visual）：连「最近一张图」一并占位，图像
        # token 真正归零；工具结果里 history/inspect 拉回的旧图也走同一
        # 分支被过滤（914-916 行的 tool_result image 过滤跟随 latest_image）。
        latest_image = (-1 if getattr(self, "turn_without_visual", False)
                        else max((index for index, message in enumerate(messages)
                                  if any(block.get("type") == "image" for block in message["content"])), default=-1))
        reduced = []
        for index, message in enumerate(messages):
            content = []
            for block in message["content"]:
                if block.get("type") == "image" and (
                        getattr(self, "turn_without_visual", False) or index < latest_image):
                    content.append({"type": "text", "text": "Earlier visual is stored in VISTA; use history/inspect with its reference if needed."})
                elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                    # 无图轮 latest_image=-1，单靠 index>=latest_image 恒真、
                    # 拦不住工具结果里的图（history/inspect 回看会把旧图带回），
                    # 必须再与 turn_without_visual 与一道。
                    keep_image = (not getattr(self, "turn_without_visual", False)
                                  and index >= latest_image)
                    result_content = [item for item in block["content"]
                                      if item.get("type") != "image" or keep_image]
                    content.append(dict(block, content=result_content))
                else:
                    content.append(block)
            reduced.append(dict(message, content=content))
        return reduced

    def _notes(self) -> str:
        notes = []
        for name in ("working_path", "guide_path"):
            path = getattr(self.runtime.context, name, None)
            if path and Path(path).is_file():
                text = Path(path).read_text(encoding="utf-8").strip()
                if text and text != "No reliable model yet.":
                    notes.append(f"[{Path(path).name}]\n{text}")
        return "\n".join(notes)

    def _investigation_fact(self) -> str:
        calls, searches, history_pages = {}, {}, []
        browser_pages, browser_observations = [], 0
        local_reads = 0
        for message in self.history:
            for block in message["content"]:
                if block.get("type") == "tool_use":
                    calls[block.get("id")] = block.get("name")
                elif block.get("type") == "tool_result":
                    name = calls.get(block.get("tool_use_id"))
                    if name not in {"basic_search", "desktop_history", "desktop_read_local",
                                    "desktop_browser_inventory", "desktop_browser_observe"}:
                        continue
                    content = block.get("content")
                    if not isinstance(content, list):
                        continue
                    try:
                        value, _ = json.JSONDecoder().raw_decode(
                            "".join(item.get("text", "") for item in content).lstrip())
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(value, dict) or block.get("is_error") or not value.get("ok"):
                        continue
                    if name == "basic_search":
                        root = str(value.get("root", "unknown"))
                        counts = searches.setdefault(root, {"calls": 0, "empty": 0, "truncated": 0})
                        counts["calls"] += 1
                        counts["empty"] += int(not value.get("matches"))
                        counts["truncated"] += int(bool(value.get("truncated")))
                    elif name == "desktop_history":
                        history_pages.append({"sources": value.get("sources"), "query": value.get("query"),
                                              "records": len(value.get("records", [])),
                                              "next_offset": value.get("next_offset"),
                                              "coverage": value.get("coverage")})
                    elif name == "desktop_browser_inventory":
                        browser_pages.append({"tabs": len(value.get("tabs", [])),
                                              "truncated": value.get("truncated")})
                    elif name == "desktop_browser_observe":
                        browser_observations += 1
                    else:
                        local_reads += 1
        if not searches and not history_pages and not local_reads and not browser_pages and not browser_observations:
            return ""
        return ("【本次会话实际取证覆盖来自已返回工具结果，不采用笔记中的自述。\n"
                + json.dumps({"directory_searches": searches, "history_pages_read": len(history_pages),
                              "browser_inventory_pages": browser_pages, "browser_observations": browser_observations,
                              "latest_history_page": history_pages[-1] if history_pages else None,
                              "local_reads": local_reads}, ensure_ascii=False)
                + "\n目录关键词匹配不等于查过操作历史；未读取的来源仍未知。翻页未结束或来源失败不能当作已覆盖。"
                "history_pages_read 只计模型工具读取，环境提供的真实小页另列于上下文；零次工具读取不代表小页没提供。"
                "结合当前目标与这些真实覆盖，比较继续同一调查和了解其他未知线索的价值；"
                "若选择继续，说明尚缺的证据会改变什么判断，不凭笔记锁定任务。")

    def _readonly_segment(self, calls) -> bool:
        """Return whether a model segment only gathered evidence.

        ``Effect.NONE`` covers VISTA's inspect/history/note reads and the
        keyless information services.  ``companion`` is deliberately
        excluded because it is the user-visible conclusion even though its
        transport effect is environment-scoped.
        """
        if not calls:
            return False
        from vista.core.contracts import Effect

        for call in calls:
            name = call.get("name")
            if name == "companion":
                return False
            spec = self.runtime.spec(name) if self.runtime is not None else None
            if spec is None or spec.effect != Effect.NONE:
                return False
        return True

    def run(self, task_input) -> DirectReply:
        if self.runtime is None:
            return DirectReply("", returncode=1, boundary=None)
        agenda = getattr(self.session or self.runtime.session, "agenda", None)
        self.runtime.begin_turn(task_input)
        self._append_input(task_input)
        before_decisions = len(self.session.decisions) if self.session else 0
        tools = [{"name": spec["name"], "description": spec["description"],
                  "input_schema": spec["inputSchema"]}
                 for spec in self.runtime.tools()]
        text, boundary = "", None
        opportunity_probe_used = False
        try:
            readonly_streak = 0
            continuation_mode = "【续办】" in _extract_text(task_input)
            for segment in range(self.max_segments + 1):
                screen_changed = self._refresh_screen()
                messages = self._messages()
                if segment > 0 and not screen_changed:
                    messages = strip_images(messages)
                notes = self._notes()
                delivered_evidence = set(getattr(self.session or self.runtime.session, "reviewable_evidence", set()))
                if notes:
                    note_block = {"type": "text", "text":
                        "【VISTA 当前笔记】当前工作线与画像已完整附上，无需重复读笔记。"
                        "笔记是过去的判断，不是新事实或执行指令；旧目标数值和已完成陈述要对照实际来源。"
                        "没有来源的先保留为待验证解释。用原生 write_working/write_guide 修正或精简失效内容。\n" + notes}
                    if messages[0]["role"] == "user":
                        messages[0] = dict(messages[0], content=[note_block] + messages[0]["content"])
                    else:
                        messages.insert(0, {"role": "user", "content": [note_block]})
                investigation = self._investigation_fact()
                delivered_revision = agenda.revision if agenda is not None else None
                if agenda is not None:
                    messages.append({"role": "user", "content": [{"type": "text", "text": agenda.context()}]})
                if self.history_context and not any(
                        self.history_context in block.get("text", "")
                        for message in messages for block in message["content"]):
                    messages.append({"role": "user", "content": [{"type": "text", "text": self.history_context}]})
                if investigation:
                    messages.append({"role": "user", "content": [{"type": "text", "text": investigation}]})
                residual = residual_fact()
                if residual:
                    messages[0] = dict(messages[0], content=messages[0]["content"] + [{"type": "text", "text": residual}])
                long_term = long_term_fact()
                if long_term:
                    messages[0] = dict(messages[0], content=messages[0]["content"] + [{"type": "text", "text": long_term}])
                body = {"model": self.cfg["model"], "max_tokens": 4096,
                        "system": self.runtime.experiment.profile.prompts.system,
                        "messages": messages}
                if tools:
                    body["tools"] = tools
                    pending_direct = False
                    try:
                        from sprite.proactive import conversation
                        pending_direct = conversation.pending_message(conversation.history(limit=12)) is not None
                    except Exception:
                        pending_direct = False
                    no_ready_goal = agenda is not None and agenda.selected() is None
                    force_opportunity_probe = (
                        segment == 0 and not opportunity_probe_used and not pending_direct and not continuation_mode
                        and self.opportunity_probe_context != self.history_context
                        and no_ready_goal and "desktop_history" in {tool["name"] for tool in tools}
                    )
                    force_companion = (
                        segment >= self.max_segments
                        or readonly_streak >= (1 if continuation_mode else self.max_readonly_segments)
                    )
                    if force_opportunity_probe and not force_companion:
                        body["tool_choice"] = {"type": "tool", "name": "desktop_history"}
                        messages.append({"role": "user", "content": [{"type": "text", "text":
                            "当前没有被证明可推进的目标。先完成一次开放机会探查：调用 desktop_history。"
                            "查看最近真实操作线索（优先 resources，小页即可），再根据结果决定是否观察浏览器读取资料或建立新目标。"
                            "已读小页不等于完整历史；结合已返回覆盖和未读游标选择取证，不重复同一首屏来宣称无事可做。"
                            "不要先读项目内开发文档来代替用户历史。"}]})
                        opportunity_probe_used = True
                    else:
                        body["tool_choice"] = (
                            {"type": "tool", "name": "companion"}
                            if force_companion else {"type": "any"}
                        )
                    if force_companion:
                        messages.append({"role": "user", "content": [{"type": "text", "text":
                            "本轮即将到达传输上限，或连续调查/失败动作没有新增可用证据。"
                            "现在调用 companion 保存进展与下一步；后台阶段可以 quiet，不要求开口。"
                            "填写 next_step（ready=下一个具体后续动作，waiting=明确缺什么，done=已完成）。"
                            "不要再调用搜索、读笔记、history，也不要只输出文字。"}]})
                started = time.perf_counter()
                payload, req = post_model(self.cfg, body)
                blocks = payload.get("content") or []
                self.history.append({"role": "assistant", "content": blocks})
                text = "".join(block.get("text", "") for block in blocks
                               if isinstance(block, dict) and block.get("type") == "text").strip()
                calls = [block for block in blocks
                         if isinstance(block, dict) and block.get("type") == "tool_use"]
                before_evidence = getattr(self.session or self.runtime.session, "evidence_revision", 0)
                read_only_batch = self._readonly_segment(calls)
                usage = payload.get("usage") or {}
                self.runtime.artifacts.record("model_usage", {
                    "segment": segment + 1, "elapsed_s": round(time.perf_counter() - started, 2),
                    "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                    "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                    "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
                    "request_bytes": len(req.data),
                    "execution_context_copies": sum(
                        block.get("text", "").count("【执行进度，不是探索方向】")
                        for message in messages for block in message["content"]),
                    "images": sum(block.get("type") == "image" for message in messages for block in message["content"]),
                    "tools": [call.get("name") for call in calls], "stop_reason": payload.get("stop_reason")})
                print(f"[brain] model segment={segment + 1} elapsed={time.perf_counter() - started:.1f}s "
                      f"tokens={usage.get('input_tokens', '?')}/{usage.get('output_tokens', '?')} "
                      f"stop={payload.get('stop_reason')} tools={[call.get('name') for call in calls]}", flush=True)
                if agenda is not None:
                    agenda.mark_delivered(delivered_revision)
                if not calls:
                    self.history.append({"role": "user", "content": [{"type": "text", "text":
                        "本轮没有收到工具调用。不要继续写分析；立即调用 companion：直接回答待回应消息，"
                        "或用 quiet 收尾并填写 next_step。不要再调用 read_guide/read_working，当前笔记已附上。"}]})
                    continue
                results = []
                for call in calls:
                    call_id = call.get("id") or f"direct-{len(self.history)}"
                    spec = self.runtime.spec(call.get("name"))
                    latest = self.live_screen.latest() if self.live_screen is not None else None
                    conversation_call = (call.get("name") == "companion"
                                         and call.get("input", {}).get("kind") != "offer")
                    reply_to = call.get("input", {}).get("reply_to") if conversation_call else None
                    from sprite.proactive import conversation
                    pending = conversation.pending_message(conversation.history(limit=12)) if reply_to else None
                    direct_reply = (pending is not None and reply_to == conversation.message_id(pending))
                    screen_dependent = call.get("name") not in {"desktop_reclaim", "desktop_write_deliverable"}
                    stale = (latest is not None and self.screen_sample is not None
                             and ((screen_dependent and not direct_reply
                                   and latest.window != self.screen_sample.window)
                                  or latest.feedback_at != self.screen_sample.feedback_at
                                  or (screen_dependent and not conversation_call and
                                      changed(self.screen_sample.thumbnail, latest.thumbnail))))
                    if conversation_call and call.get("input", {}).get("kind") == "quiet":
                        stale = False
                    from vista.core.contracts import Effect
                    if boundary or (stale and spec is not None and spec.effect == Effect.ENVIRONMENT):
                        if boundary:
                            blocked_text = "未执行：这一轮已经结束。"
                        else:
                            stale_key = action_key(
                                str(call.get("name") or ""),
                                call.get("input") if isinstance(call.get("input"), dict) else {})
                            self.stale_state, blocked_text = note_stale_block(
                                getattr(self, "stale_state", {}), stale_key, now=time.time())
                        results.append({"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                                        "content": [{"type": "text", "text": blocked_text}]})
                        continue
                    if (call.get("name") == "desktop_review_evidence"
                            and call.get("input", {}).get("id") not in delivered_evidence):
                        results.append({"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                                        "content": [{"type": "text", "text":
                                            "请先接收并查看截图工具返回的实际图片，再核验；不能在同一请求中预先过未见截图。"}]})
                        continue
                    execution = self.runtime.execute(call.get("name"), call.get("input", {}), call_id)
                    if (execution.success and spec is not None and spec.effect == Effect.ENVIRONMENT
                            and isinstance(call.get("input"), dict)):
                        self.stale_state = note_stale_success(
                            getattr(self, "stale_state", {}),
                            action_key(str(call.get("name") or ""), call.get("input")))
                    if (call.get("name") == "desktop_history" and execution.success
                            and force_opportunity_probe and not force_companion):
                        requested_snapshot = call.get("input", {}).get("snapshot")
                        try:
                            current_snapshot = json.loads(self.history_context.splitlines()[1]).get("snapshot")
                        except (ValueError, IndexError, AttributeError):
                            current_snapshot = None
                        if not requested_snapshot or requested_snapshot == current_snapshot:
                            self.opportunity_probe_context = self.history_context
                    result_content = [{"type": "text", "text": execution.text}]
                    if spec is None:
                        result_content.append({"type": "text", "text":
                            "这个工具未提供，不能执行。实际可用工具：" + ", ".join(tool["name"] for tool in tools)
                            + "。用实际工具补证据；能力缺口如实保留，不能猜工具名当作行动。"})
                    for visual in execution.images:
                        if visual.get("steer_text"):
                            result_content.append({"type": "text", "text": visual["steer_text"]})
                        result_content.append({"type": "image", "source": {
                            "type": "base64", "media_type": visual["mime_type"], "data": visual["data"]}})
                    results.append({"type": "tool_result", "tool_use_id": call_id,
                                    "content": result_content,
                                    "is_error": not execution.success})
                    self.runtime.acknowledge(call_id)
                    if execution.interrupt_after:
                        boundary = execution.boundary_reason
                self.history.append({"role": "user", "content": results})
                new_evidence = getattr(self.session or self.runtime.session, "evidence_revision", 0) != before_evidence
                failed_batch = bool(results) and all(result.get("is_error") for result in results)
                readonly_streak = readonly_streak + 1 if (read_only_batch or failed_batch) and not new_evidence else 0
                if boundary:
                    break
        except ModelRateLimited:
            self.rate_limited_until = time.time() + RATE_LIMIT_COOLDOWN_S
            print("[brain] model rate-limited; giving up on this turn", flush=True)
            return DirectReply("", returncode=1, boundary=None, rate_limited=True)
        except Exception as exc:
            reason = getattr(exc, "reason", exc)
            detail = str(reason).replace(str(self.cfg.get("api_key") or "<unset>"), "[redacted]")[:240]
            print(f"[brain] direct model call failed: {type(exc).__name__}/{type(reason).__name__}: {detail}", flush=True)
            return DirectReply(text, returncode=1, boundary=boundary)
        if self.session and len(self.session.decisions) > before_decisions:
            decision = self.session.decisions[-1]
            self.runtime.artifacts.record("turn_outcome", {
                "kind": decision.get("kind"), "next_step": decision.get("next_step"),
                "actions": self.session.actions, "segments": segment + 1})
        return DirectReply(text, returncode=0 if boundary else 1, boundary=boundary)


DirectBackend = VisualDirectBackend


def continuation_key(decision: dict) -> str | None:
    step = decision.get("next_step") or {}
    if step.get("status") != "ready" or not step.get("action"):
        return None
    identity = ({"tool": step["tool"], "arguments": step.get("arguments", {})} if step.get("tool")
                else {"goal": step.get("goal"), "action": step["action"]})
    if step.get("goal_id"):
        identity.update(goal_id=step["goal_id"], phase=step.get("phase"), evidence=step.get("evidence"),
                        result_version=step.get("result_version"))
    return json.dumps(identity, sort_keys=True, ensure_ascii=False)


class ContinuationTracker:
    def __init__(self):
        self.attempted = set()
        self.step = None

    def pending(self, decision: dict, revision: int, agenda=None) -> str | None:
        candidates = agenda.continuation_steps() if agenda is not None else []
        step = decision.get("next_step") or {}
        registered = agenda is not None and any(
            agenda.matches(replace(goal, state=state), step.get("tool"), step.get("arguments", {}))
            for goal in agenda.goals.values() for state in ("ready", "verify"))
        if not registered and step.get("status") == "ready" and step.get("action"):
            candidates.append(step)
        self.step = None
        for step in candidates:
            key = continuation_key({"next_step": step})
            seen = (any(attempted_key == key for attempted_key, attempted_revision in self.attempted)
                    if step.get("goal_id") else (key, revision) in self.attempted)
            if key and not seen:
                self.step = step
                return key
        return None

    def consume(self, key: str, revision: int) -> None:
        self.attempted.add((key, revision))


CLAUDE_BACKENDS = {"claude", "host"}
# Historical aliases that still mean the direct HTTP path, including an empty value.
BACKEND_DIRECT_VALUES = {"", "1", "true", "yes", "on", "direct"}


def backend_kind(env=None) -> str:
    """direct unless OPENLOOKOUT_BACKEND is claude or host.

    An empty value is direct. host remains an alias of claude. Unknown values
    stay on direct so a typo cannot start Claude Code.
    """
    env = os.environ if env is None else env
    raw = str(env.get("OPENLOOKOUT_BACKEND", "")).strip().lower()
    if raw in CLAUDE_BACKENDS:
        return "claude"
    return "direct"


def chosen_model(cfg: dict, env=None) -> str:
    """provider.json model, unless OPENLOOKOUT_MODEL is a non-blank override."""
    env = os.environ if env is None else env
    override = str(env.get("OPENLOOKOUT_MODEL") or "").strip()
    if override:
        return override
    return str((cfg or {}).get("model") or "").strip()


def build(cfg: dict, root: Path):
    """建立持续会话。

    默认直接请求 provider.json 里的协议端点。只有 OPENLOOKOUT_BACKEND=claude
    （host 是别名）才走本机 Claude Code。Claude 起不来就报错，不改走直连；
    直连缺配置也不改走 Claude。
    """
    from vista.benchmarks.desktop.profiles import make_experiment, make_profile
    from vista.benchmarks.desktop.session import DesktopSession
    from vista.core.runtime import TaskRuntime
    session = DesktopSession("你是陪在用户身边的小精灵：结合持续画面与真实操作痕迹理解目标，自主发现值得帮助的事情、准备下一步；看准时机交流或报告有用的结果。", {})
    model = chosen_model(cfg)
    selected_cfg = {**cfg, "model": model, "protocol": (cfg or {}).get("protocol") or "anthropic"}
    exp = make_experiment(make_profile(), backend="claude", model=model, effort="low", revision="0.1", presentation={})
    runtime = TaskRuntime(session, exp, artifact_dir=root / "artifacts")
    if backend_kind() != "claude":
        print("[brain] direct mode: HTTP to the configured provider, no Claude Code", flush=True)
        direct_backend = VisualDirectBackend(selected_cfg, runtime)
        direct_backend.mode = "direct-configured"
        return session, runtime, direct_backend, "direct-configured"
    if os.environ.get("OPENLOOKOUT_NO_DOCKER_MCP", "").lower() in {"1", "true", "yes", "on"}:
        print("[brain] Claude Code mode without Docker or MCP", flush=True)
        return session, runtime, LocalClaudeTextBackend(selected_cfg, runtime), "host-local-no-mcp"
    from vista.backends.claude import create_backend
    from vista.backends.claude.provider import LOCAL_HOST_PROVIDER
    from vista.backends.claude.runner import default_claude_bin
    configured = os.environ.get("OPENLOOKOUT_CLAUDE_BIN") or shutil.which("claude")
    binary = Path(configured) if configured else default_claude_bin()
    os.environ.setdefault("OPENLOOKOUT_ALLOW_UNSAFE_HOST_MODE", "1")
    backend = create_backend(
        runtime, directory=root / "transport", oauth_token=None,
        binary=binary, image="arc3-claude-player:0.1",
        provider=LOCAL_HOST_PROVIDER, provider_credential=None, provider_base_url=None,
        max_output_tokens=2048, ca_bundle=Path(certifi.where()), host_mode=True,
        task_timeout=TURN_TIMEOUT_S, decision_lease_timeout=DECISION_LEASE_S,
        host_builtin_tools=os.environ.get("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", ""))
    print(f"[brain] Claude backend: host-native ({binary})", flush=True)
    return session, runtime, backend, "host-native-unsandboxed"


def restore_guide(runtime, ledger=None) -> None:
    """把上次保存的长期理解放回本次会话的 GUIDE.md。

    ledger 给定时（隐性教练，issue #18）：拷回后重新剥离/合并教练围栏块——
    模型上一轮的全量 write_guide 可能丢块，规范块以内存账本为准补回。
    """
    if GUIDE.exists() and runtime.context.guide_path:
        shutil.copyfile(GUIDE, runtime.context.guide_path)
        if ledger is not None:
            guide_path = Path(runtime.context.guide_path)
            guide_path.write_text(
                coach.merge_block(guide_path.read_text(encoding="utf-8"), ledger),
                encoding="utf-8")
    if WORKING.exists() and runtime.context.working_path:
        shutil.copyfile(WORKING, runtime.context.working_path)


def save_guide(runtime, ledger=None) -> None:
    gp = runtime.context.guide_path
    if gp and Path(gp).exists():
        COMPANION.mkdir(parents=True, exist_ok=True)
        if ledger is None:
            shutil.copyfile(gp, GUIDE)
        else:
            # 先剥离模型可能仿造/残留的教练块，再追加内存账本的规范块；
            # 同一份合并文本写回会话文件与持久副本，块在任何覆盖下都不丢。
            merged = coach.merge_block(Path(gp).read_text(encoding="utf-8"), ledger)
            Path(gp).write_text(merged, encoding="utf-8")
            GUIDE.write_text(merged, encoding="utf-8")
    wp = runtime.context.working_path
    if wp and Path(wp).exists():
        COMPANION.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wp, WORKING)


def load_coach_ledger() -> dict:
    """从持久 GUIDE.md 的教练围栏块恢复账本；没有块就是空账本。"""
    try:
        if GUIDE.exists():
            return coach.parse_block(GUIDE.read_text(encoding="utf-8")) or coach.new_ledger()
    except OSError:
        pass
    return coach.new_ledger()


_COACH_JSONL_CACHE: dict[str, dict] = {}


def _cached_jsonl_rows(path: Path, cache: dict | None = None) -> list[dict]:
    """mtime/size 缓存读 jsonl：文件没变就不重读（P2-5，文件会无限增长）。

    stamp 用 (mtime_ns, size)：只追加不改写的账本在 size 不变时内容必然没变；
    任何读取失败都退化成空表，缓存按路径隔离且不上锁，教练回流不能炸主循环。
    """
    key = str(path)
    slot = cache if cache is not None else _COACH_JSONL_CACHE.setdefault(key, {})
    try:
        stat = path.stat()
    except OSError:
        slot.clear()
        return []
    stamp = (stat.st_mtime_ns, stat.st_size)
    if stamp == slot.get("stamp"):
        return slot.get("rows", [])
    rows = _rows(path)
    slot["stamp"], slot["rows"] = stamp, rows
    return rows


def _published_coach_offers(path: Path | None = None) -> set:
    """实际发布上屏的气泡键集合 {(topic, t)}（offers.jsonl 的 result=shown 行）。

    被 help 层判重抑制的决策没有 shown 行（session.py:200-216 的发布点不查
    账本，本进程不能改它），用这个键在事后区分「真上屏」与「没上屏」：没上屏
    的 coach 决策不得 mark_spoken（P2-4）。
    """
    path = path or OFFERS
    return {coach.published_key(row.get("topic"), row.get("t"))
            for row in _cached_jsonl_rows(path)
            if row.get("result") == "shown"}


def sync_coach(ledger, session, *, seen_decisions: int, now: float,
               surface: bool, outcomes_path: Path | None = None,
               offers_path: Path | None = None, new_stay: bool = False) -> int:
    """每轮 companion 决策后调用：topic 约定 → 确定性账本迁移 + outcomes 回流。

    接线刻意薄：模型判断「这件事算不算某模式的证据」与教练话措辞；状态迁移
    全部在 coach.py 的纯函数里。surface 是本轮是否处在允许教练开口的时刻
    （断点/等待；非流中、非离开、非回话轮），由主循环的时机信号算出。
    new_stay 表示观察到「人已离开」：上一次停留结束，清除段内开口抑制。
    发布核验用 offers.jsonl 的 shown 行（两侧同一 coach.published_key
    规范化，避免带空白 topic 误判），outcomes/offers 都按 mtime/size
    缓存，避免每轮 O(n) 全量扫。返回已消费到的 decisions 下标。
    """
    if new_stay:
        coach.reset_stay(ledger)
    decisions = list(getattr(session, "decisions", [])[seen_decisions:])
    published = _published_coach_offers(offers_path)
    for row in coach.apply_decisions(ledger, decisions, now,
                                     surface=surface, published=published):
        print(f"[brain] coach 违规开口被工程闸拦下（不迁移状态）：{row['id']} {row['reason']}", flush=True)
    path = outcomes_path or (PERCEIVE / "outcomes.jsonl")
    for row in _cached_jsonl_rows(path):
        state = coach.apply_outcome(
            ledger, event_id=row.get("id"), topic=row.get("topic"),
            outcome=row.get("outcome"), now=_event_time(row.get("t")) or now)
        if state:
            print(f"[brain] coach outcome {row.get('topic')} -> {state} ({row.get('outcome')})", flush=True)
    return len(getattr(session, "decisions", []))


def save_current(session) -> None:
    """Expose the latest model judgment to the companion window."""
    if not session.decisions:
        return
    decision = session.decisions[-1]
    PERCEIVE.mkdir(parents=True, exist_ok=True)
    row = {
        "t": decision.get("t", time.time()),
        "activity": str(decision.get("activity") or "").strip(),
        "state": str(decision.get("state") or "").strip(),
        "topic": str(decision.get("topic") or "").strip(),
        "confidence": float(decision.get("confidence", 0.0) or 0.0),
        "kind": decision.get("kind", "quiet"),
        "say": str(decision.get("say") or "").strip(),
        "source": "vista",
        "next_step": session.public_next_step(decision.get("next_step")) if hasattr(session, "public_next_step") else decision.get("next_step"),
        "speech": decision.get("speech", {"kind": decision.get("kind", "quiet")}),
        "work": session.work_summary() if hasattr(session, "work_summary") else decision.get("work"),
    }
    temporary = PERCEIVE / "current.json.tmp"
    try:
        temporary.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        temporary.replace(PERCEIVE / "current.json")
    except OSError:
        # A transient GUI read must never stop the visual loop.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def reset_current() -> None:
    """Avoid showing a previous session's stale judgment while a new one starts."""
    PERCEIVE.mkdir(parents=True, exist_ok=True)
    temporary = PERCEIVE / "current.json.tmp"
    row = {"t": time.time(), "activity": "正在重新看当前画面", "state": "新会话已启动，正在建立连续上下文", "source": "vista"}
    try:
        temporary.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        temporary.replace(PERCEIVE / "current.json")
    except OSError:
        temporary.unlink(missing_ok=True)


def run() -> None:
    from vista.benchmarks.desktop.session import screen_visual
    from vista.core.profiles import Phase
    bootstrap_dotenv()  # .env 本地开关随本进程生效；真实环境变量优先
    problem = provider_problem()
    if problem:
        print(problem, flush=True)
        raise SystemExit(2)
    _p = load_provider()
    cfg = {"model": _p.model, "base_url": _p.base_url, "api_key": _p.api_key, "protocol": _p.protocol}
    root = COMPANION / "runs" / time.strftime("%Y%m%d-%H%M%S")
    session, runtime, backend, mode = build(cfg, root)
    if hasattr(backend, "attach"):
        backend.attach(session)
    live_screen = LiveScreen() if isinstance(backend, VisualDirectBackend) else None
    if live_screen is not None:
        live_screen.start()
        backend.live_screen = live_screen
        backend.screen_sample = live_screen.latest()
        backend.screen_revision = backend.screen_sample.revision
    # 隐性教练账本（issue #18）：从 GUIDE.md 围栏块恢复，会话期间由确定性
    # 代码维护，save_guide 时剥离/合并，模型全量 write_guide 也不丢块。
    coach_ledger = load_coach_ledger()
    restore_guide(runtime, coach_ledger)
    reset_current()
    reader = watching.load(COMPANION)
    sysw = systemfacts.load(COMPANION)
    maintenance = MaintenanceSignal(sysw)
    policy = DecisionEngine.load(COMPANION / "decision_state.json")
    agenda = Agenda.load(policy, COMPANION / "agenda.json")
    session.agenda = agenda
    desktopw = desktopfacts.load()
    from .historyfacts import HistoryFeed
    historyw = HistoryFeed()
    history_line = historyw.observe(time.time())
    if isinstance(backend, VisualDirectBackend):
        backend.history_context = historyw.context
    print(f"[brain] 会话已建立（{mode}通道）：持续视觉上下文开始", flush=True)
    initial_now = time.time()
    initial_maintenance = maintenance.observe(initial_now, refresh=True)
    initial_revision = agenda.revision
    startup_feedback = new_feedback(backend.feedback_since if live_screen else initial_now)
    if model_turn_due(maintenance_due=bool(str(initial_maintenance).strip()), feedback=startup_feedback):
        print("[brain] initial turn: preparing VISTA input", flush=True)
        initial_result = backend.run(runtime.prepare_input(Phase.INITIAL, public_text=conversation_fact(
            idle_s=watching.idle_seconds(), now=time.time()) + "\n" + history_line
            + "\n" + initial_maintenance + "\n" + agenda.context(),
            observation=session.observe(backend.screen_sample.visual) if live_screen is not None else None))
    else:
        print("[brain] waiting: screen unchanged and no trigger, so no model call", flush=True)
        initial_result = DirectReply(boundary=None)
    if not isinstance(backend, VisualDirectBackend) and initial_result.boundary is not None:
        agenda.mark_delivered(initial_revision)
    # 初始轮是建立上下文，不是操作流断点：教练开口闸关闭（quiet 记实例/退休
    # 信号照常回流），防止「一启动就说教」。
    coach_seen = sync_coach(coach_ledger, session, seen_decisions=0,
                            now=time.time(), surface=False)
    save_guide(runtime, coach_ledger)
    save_current(session)
    if initial_result.boundary is not None:
        maintenance.consume()
    if live_screen is not None and getattr(backend, "screen_sample", None) is not None:
        seeded_thumb = backend.screen_sample.thumbnail
    else:
        try:
            seeded_thumb = thumb(screen_visual())
        except Exception:
            seeded_thumb = None
    last_thumb, last_turn, last_fb = seeded_thumb, time.time(), backend.feedback_since if live_screen else time.time()
    # 上一次**真的把截图送进模型**的时刻：纯文本轮不刷它，静止屏幕靠
    # VISUAL_RECHECK_S 兜底刷新视觉上下文。
    last_visual_turn = time.time()
    turn_count = 0
    last_window = None
    desktop_pending, desktop_line = False, ""
    previous_idle_s = 0.0
    continuations = ContinuationTracker()
    history_line = ""
    tt = timing_tracker()
    try:
        while not runtime.terminal:
            time.sleep(2)
            if quit_requested(HOME):
                print("[brain] quit requested; stopping", flush=True)
                break
            if paused(HOME):
                continue
            now = time.time()
            if now < float(getattr(backend, "rate_limited_until", 0) or 0):
                continue
            sample = live_screen.latest() if live_screen is not None else None
            vis = sample.visual if sample is not None else screen_visual()
            th = thumb(vis)
            if last_thumb is None:
                last_thumb = th
            sig = watching.foreground()
            window_key = (sig.get("proc", ""), sig.get("title", ""))
            window_due = last_window is not None and window_key != last_window and now - last_turn >= MIN_GAP_S
            last_window = window_key
            desktop_observation = desktopw.observe(now)
            if desktop_observation.should_emit:
                desktop_pending, desktop_line = True, desktop_observation.line()
            fb = new_feedback(last_fb)
            # A return from the away state is a meaningful context change even
            # when the screen thumbnail is identical.  Without this edge the
            # next conversation waits for the heartbeat interval.
            return_due = (previous_idle_s >= watching.DEFAULTS["away_s"] and
                          watching.idle_seconds() < watching.DEFAULTS["away_s"])
            current_idle_s = watching.idle_seconds()
            previous_idle_s = current_idle_s
            screen_due = changed(last_thumb, th) and now - last_turn >= MIN_GAP_S
            background_due = desktop_pending and now - last_turn >= MIN_GAP_S
            maintenance.observe(now)
            maintenance_due = maintenance.pending and now - last_turn >= MIN_GAP_S
            history_line = historyw.observe(now) or history_line
            if isinstance(backend, VisualDirectBackend):
                backend.history_context = historyw.context
            history_due = bool(history_line) and now - last_turn >= MIN_GAP_S
            # 先于本轮 last_turn 重置捕获真实间隔：心跳文案里的「距上一轮判断
            # 已 X 分钟」必须用它，不能用键鼠 idle（见 heartbeat_note 说明）。
            turn_gap_s = now - last_turn
            heartbeat_due = heartbeat_is_due(now, last_turn)   # 兜底，不是主触发；以轮末为基准
            timing_due, timing_why = False, ""
            timing_moment = None       # 教练开口时刻闸用：fire=断点，detail.busy=流中
            if tt is not None:
                try:
                    mo = tt.consider(ops_events(now=now), now)
                    timing_moment = mo
                    if mo.fire:
                        # 把触发的具体对象」一并交给模型，否则它只能泛泛谈（见 GUIDE.md「别做指标触发）
                        try:
                            _d = mo.detail or {}
                            _bits = [str(v).strip() for v in (
                                _d.get("trigger_app"), _d.get("trigger_type"), _d.get("trigger_title")) if v]
                            _anchor = "/".join(_bits)
                            if _anchor or mo.key:
                                timing_why_extra = f"（触发对象：{_anchor or '未知'}，键 {mo.key}）"
                            else:
                                timing_why_extra = ""
                        except Exception:
                            timing_why_extra = ""
                        timing_due, timing_why = True, mo.why + timing_why_extra
                        print(f"[brain] timing fire kind={mo.kind} V={mo.score:.3f} {mo.why} "
                              f"key={mo.key} anchor={timing_why_extra}", flush=True)
                    try:
                        # 台账记录「状态变化」，不是定时轮询：fire 时写，或判定种类变了时写一次。
                        if mo.fire or mo.kind != TIMING_CACHE.get("verdict_kind"):
                            TIMING_CACHE["verdict_kind"] = mo.kind
                            with open(PERCEIVE / "timing.jsonl", "a", encoding="utf-8") as fh:
                                fh.write(json.dumps({"t": now, **mo.to_dict()},
                                                    ensure_ascii=False) + "\n")
                    except OSError:
                        pass
                except Exception as exc:
                    print(f"[brain] timing 判断失败：{exc!r}", flush=True)
            prep_due = (not fb) and (maintenance_due or history_due or heartbeat_due or (turn_count and turn_count % PREP_EVERY_TURNS == 0))
            decision = session.decisions[-1] if session.decisions else {}
            evidence_revision = getattr(session, "evidence_revision", 0)
            goal_due = agenda.due()
            step_key = continuations.pending(decision, evidence_revision, agenda)
            continue_due = step_key is not None and not fb
            # A message he is waiting on is a trigger in its own right.  Without
            # this, a still screen and a healthy model both look like "nothing to
            # do", and the message waits for the next unrelated event -- measured
            # 52.8s on 10-13 purely because the loop had no reason to wake up.
            #
            # Two separate things, deliberately not one:
            #   reply_pending -- someone is waiting.  Makes this turn a reply turn.
            #   reply_due     -- the wait is nearly up.  Additionally wakes the loop.
            # Priority has to start at the first tick, otherwise the turn that
            # happens to be running when he writes is the one that wastes its
            # budget investigating, and the reply lands a turn late.  Only the
            # deadline is allowed to add a wakeup, so a quiet screen still costs
            # nothing until the wait is genuinely long.
            reply_age = pending_reply_age(now)
            reply_pending = reply_age is not None
            reply_due = reply_pending and (REPLY_DEADLINE_S - reply_age) <= MIN_GAP_S
            # 两级模型轮：只有强视觉信号才把新截图送进模型；纯心跳/维护/
            # 续办轮是无图文本轮（watching 计时事实是纯文本，照样够判断）。
            visual_wanted = turn_wants_visual(
                screen_due=screen_due, window_due=window_due, timing_due=timing_due,
                fb=fb, return_due=return_due, reply_due=reply_due,
                now=now, last_visual_turn=last_visual_turn,
                reply_text=pending_reply_text(now) if reply_due else None)
            if not model_turn_due(
                screen_due=screen_due,
                window_due=window_due,
                background_due=background_due,
                maintenance_due=maintenance_due,
                timing_due=timing_due,
                feedback=fb,
                return_due=return_due,
                continue_due=continue_due,
                goal_due=bool(goal_due),
                reply_due=reply_due,
            ):
                continue
            if continue_due:
                continuations.consume(step_key, evidence_revision)
            if tt is not None:
                try:
                    tt.commit(now)
                except Exception:
                    pass
            last_thumb, last_turn = th, now
            turn_count += 1
            if fb: last_fb = now
            rf = watching_fact(reader, th)
            watching.save(reader, HOME)
            sf = maintenance.observe(now, refresh=True)
            systemfacts.save(sysw, HOME)
            df = desktop_line if desktop_pending else ""
            desktop_pending, desktop_line = False, ""
            mf = memory_fact()
            idle_s = current_idle_s
            if prep_due and not reply_pending:
                cycle = idle_scan_fact(heartbeat=True, idle_s=idle_s, now=now)
                # 心跳轮过去一律叫「背景准备轮」，配合下面那段「默认安静」，
                # 等于每 4 分钟告诉模型一次闭嘴。名字本身就在带偏判断：
                # 这一轮首先是「重新看一眼他现在的状态」，准备只是其中一项可能。
                # PR #16 复审 P2-1：away 轮同屏的 watching 事实是「别打扰，
                # 回来再说」，lead 若还写「也可能是自然开口的窗口」就是正面冲突——
                # away 时 lead 不得鼓励开口，措辞按 idle 阈值分流。
                away = idle_s >= watching.DEFAULTS["away_s"]
                if away:
                    lead = ("这是兜底心跳轮：重新判断此刻的状态。"
                            "他已久未操作，可能暂离；别打扰，回来再说，"
                            "本轮只做不发声的后台准备。")
                elif visual_wanted:
                    # 900s 兜底的带图心跳：有新画面，正常重新感知，不发
                    # 「时间到了可以说话」的许可证（文案见 hb 分支）。
                    lead = "这是兜底心跳轮：屏幕久未真正变化，重新看一眼此刻的状态。"
                else:
                    lead = ("这是无图兜底心跳轮：本轮没有新画面，"
                            "只核对时间事实与后台状态；时间到了不是开口理由。")
            else:
                cycle = ""
                lead = "这是回话轮：他在等你回答。" if reply_pending else "这是本次实时工作轮。"
            look_hint = ("先看 CURRENT，需要时用 history 回看之前的画面；"
                         if visual_wanted else
                         "本轮没有新画面，也不要为了找话题回看历史画面；")
            text = ((fb + "\n") if fb else "") + lead + look_hint + "再用 companion 工具决定此刻说什么（或安静）。"
            if reply_pending:
                # Whoever triggered this turn, answering him is the whole job.
                # Without this the model keeps its old objective, spends the turn
                # investigating, and the reply slips to the following turn --
                # which is exactly the 52.8s this priority exists to prevent.
                text += ("\n【优先回话】他在上一条之后还没有收到你的回答，本轮就是为这句而来。"
                         "已有依据就直接回答，不要先做全量扫描、读整份笔记或检索；"
                         "确实缺的证据就只补那一处，然后回答。"
                         "这一轮不要 quiet：除非他这句话已经作废（比如你确认他已自己处理完），否则必须回。")
            if continue_due:
                text += "\n【续办】这是你选择的可继续下一步，不等待页面变化或用户开口：" + json.dumps(
                    continuations.step, sort_keys=True, ensure_ascii=False)
                text += "。先推进并核对结果，再根据新增证据决定继续改进或换方向安静准备也应推进；只有工具无法自行取得的外部条件才等待。"
            if cycle:
                text += "\n" + cycle
            if mf: text += "\n" + mf
            if rf: text += "\n" + rf
            if sf: text += "\n" + sf
            if df: text += "\n" + df
            if history_line: text += "\n" + history_line
            history_line = ""
            text += "\n" + conversation_fact(idle_s=idle_s, now=now)
            # 心跳专用「自然开口窗口」提示的排除条件都收在 heartbeat_note_if_due：
            # reply_pending / away（watching 已要求「别打扰」）/ 有锚点轮次一律不附。
            hb_note = heartbeat_note_if_due(
                heartbeat_due=heartbeat_due, turn_gap_s=turn_gap_s, idle_s=idle_s,
                reply_pending=reply_pending, fb=fb, return_due=return_due,
                continue_due=continue_due, goal_due=bool(goal_due),
                has_visual=visual_wanted)
            if timing_why:
                text += ("\n【为什么是现在】" + timing_why
                         + "。这是由行为事件边界触发的时刻（不是定时轮）。"
                         + "若此刻没有值得说的，就安静——quiet 是正确结果，不是失败。"
                         + "若要开口：第一句必须点名这次触发的**具体对象**（刚保存的文件、刚复制的内容、"
                         + "刚切换到的应用/窗口标题之一），让用户一眼看出你是因这件事、在这个时刻开口；"
                         + "拿不到具体对象就不要开口。结尾不要问「要不要我做……」，"
                         + "能自己做的就自己做完再说结果。")
            elif hb_note:
                # 兜底心跳轮的完整说明（为什么不能再写「默认安静」、数字为什么
                # 用距上轮时间而不是键鼠 idle、哪些轮次必须排除）都在
                # heartbeat_note / heartbeat_note_if_due 的 docstring 里。
                text += hb_note
            elif not reply_pending and not (fb or return_due or continue_due or goal_due):
                # 背景准备/维护轮，以及人已离开（away）的心跳轮：这些不是行为
                # 边界，watching 事实在 away 时还附了「别打扰，回来再说」，
                # 仍然偏向安静。reply_pending 轮也不进来——上面的【优先回话】
                # 已经要求「这一轮不要 quiet」，再附「默认安静」会自相矛盾。
                text += ("\n【注意：本轮不是行为边界触发的】没有用户刚做的事作为锚点，"
                         "默认安静。只有当你手上有一个**已经核对过、且必须让他现在知道**的具体结果时"
                         "才开口，否则 quiet；不要用指标、进度或对别的文档的评论充当开口理由。")
            # allowlist: the model decides from the current visual/history
            # context, while quiet remains the safe choice without evidence.
            text += ("\n[Decision guidance] This is not a status broadcast. "
                     "Use the CURRENT visual and recent operations to understand what the user is pursuing. "
                     "If there is a relevant, evidence-backed idea or question, a natural companion message is allowed; "
                     "if a concrete reversible action would help, offer it. Otherwise choose quiet. "
                     "Do not invent a topic, weather update, or generic activity report.")
            text += "\n" + agenda.context()
            # 隐性教练时刻闸（issue #18）：教练话只允许出现在行为事件边界
            # （timing fire 已过 settle）或人在但停手的等待时刻；操作流中、
            # 离开、回话轮一律不把教练段送进提示词——红线上就没有开口路径。
            coach_away = idle_s >= watching.DEFAULTS["away_s"]
            coach_busy = bool((timing_moment.detail or {}).get("busy")) if timing_moment is not None else False
            coach_gate = {"boundary": timing_due,
                          "settled": bool(heartbeat_due) and not coach_away and idle_s >= coach.WAIT_IDLE_S,
                          "in_flow": coach_busy and not timing_due,
                          "away": coach_away, "reply_pending": reply_pending}
            coach_text = coach.surface_note(coach_ledger, now, **coach_gate)
            if coach_text:
                text += "\n" + coach_text
            # 无图轮：不消费画面 revision——这一帧没送进模型，
            # _refresh_screen/下一轮仍会把它作为新 CURRENT 送达；
            # feedback_since 每次都刷（文字反馈本轮确实已附上）。
            if isinstance(backend, VisualDirectBackend):
                backend.turn_without_visual = not visual_wanted
            if sample is not None:
                if visual_wanted:
                    backend.screen_revision = sample.revision
                    backend.screen_sample = sample
                backend.feedback_since = now
            offered_revision = agenda.revision
            r = backend.run(runtime.prepare_input(
                Phase.STEP, public_text=text,
                observation=session.observe(vis) if visual_wanted else None))
            if getattr(r, "rate_limited", False) or getattr(r, "api_error_status", None) == 429:
                arm_rate_limit(backend)
            # 轮末再刷一次 last_turn（轮首 1516 行那次之外）：一轮可达
            # TURN_TIMEOUT_S=300s > HEARTBEAT_S=240s，只记轮首的话，超时轮
            # 结束的下一个 tick 立即满足心跳，背靠背再开一轮。以轮末为基准后，
            # 心跳间隔才真的是 240s；MIN_GAP_S 节流同理按轮末算。
            # 详见 heartbeat_is_due 的 docstring。
            last_turn = time.time()
            # 带图轮记账：计划附图、或调查中 _refresh_screen 注入了新画面
            # （会把 turn_without_visual 清成 False）都算视觉上下文已刷新。
            visual_delivered = visual_wanted or (
                isinstance(backend, VisualDirectBackend) and not backend.turn_without_visual)
            if visual_delivered:
                last_visual_turn = last_turn
            if not isinstance(backend, VisualDirectBackend) and r.boundary is not None:
                agenda.mark_delivered(offered_revision)
            if live_screen is not None:
                last_fb = backend.feedback_since
                last_thumb = backend.screen_sample.thumbnail
            if r.boundary is not None:
                maintenance.consume()
            # 决策回流：coach topic 约定做确定性迁移，outcomes.jsonl 回流采纳/
            # 拒绝/超时；随后合并围栏块并持久化（先迁移后存盘，块与账本一致）。
            coach_seen = sync_coach(coach_ledger, session, seen_decisions=coach_seen,
                                    now=last_turn,
                                    surface=coach.surface_allowed(**coach_gate)[0],
                                    new_stay=coach_gate["away"])
            save_guide(runtime, coach_ledger)
            save_current(session)
            print(f"[brain] turn done boundary={r.boundary} decisions={len(session.decisions)}", flush=True)
    finally:
        if live_screen is not None:
            live_screen.close()
        save_guide(runtime, coach_ledger)
        watching.save(reader, HOME)
        systemfacts.save(sysw, HOME)
        runtime.close()


if __name__ == "__main__":
    run()

