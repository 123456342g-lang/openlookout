"""小精灵的大脑：一个长期运行的 VISTA 会话。
- 同一个模型会话持续存在；VISTA 保存每一帧原始画面（视觉记忆），模型可history / inspect 回看。
- 每次屏幕有明显变化，就以 STEP 轮次喂给同一个会话；模型用companion 工具决定“说话/提议/安静”。
- GUIDE.md（对用户的长期理解）跨重启保留在 sprite_home/companion/GUIDE.md?  用户的反馈（好的/不用/纠正）以文字追加进下丢轮，只作为权衡依据，不是命令?- 上下文快满时?VISTA 自己交接，不重开会话；进程崩溃才重启?python -m vista.benchmarks.desktop.brain
"""
from __future__ import annotations

import json, math, os, shutil, threading, time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import certifi

from . import desktopfacts, memory, systemfacts, watching
from .decision_engine import DecisionEngine
from .agenda import Agenda

HOME = Path(os.environ.get("SPRITE_HOME", r"E:\OpenLookout\sprite_home"))
COMPANION = HOME / "companion"
GUIDE = COMPANION / "GUIDE.md"
WORKING = COMPANION / "WORKING.md"
PERCEIVE = HOME / "perceive"
FEEDBACK = PERCEIVE / "feedback.jsonl"
OFFERS = PERCEIVE / "offers.jsonl"
PROJECT = Path(__file__).resolve().parents[3]
CHANGE_MIN = 0.01          # 屏幕缩略图平均差异超?1% 就重新判?MIN_GAP_S = 5              # 页面切换后尽快跟上；节流交给模型判断和输出闸
HEARTBEAT_S = 900          # 兜底心跳：主触发已交?sprite/proactive/timing.py 的事件边界算?PREP_EVERY_TURNS = 24      # rotate one background scan even during a busy screen
# Use the configured provider model.  Hard-coding an alias here made Claude
# return a 400 when the endpoint did not publish that model id.
ACTIVE_MODEL = "mimo-v2.6-flash"


def thumb(visual) -> list[int]:
    import io
    from PIL import Image
    return list(Image.open(io.BytesIO(visual.data)).convert("L").resize((48, 30)).getdata())


def changed(a, b) -> bool:
    return a is None or sum(abs(x - y) for x, y in zip(a, b)) / (len(a) * 255) >= CHANGE_MIN


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
    """惰创建时机追踪器；导入失败化成 None（大脑照常跑，只是回到旧的心跳触发）?
    timing v2：时效按「我们第丢次看见这条事件的时刻算，而不是它自称发生的时刻?    记录器把 focus 区间写在结束时却用开始时刻做 ts，不这样改，丢个刚刚才可行动的边界会被算成过期?    """
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
    """【此刻的异常?s_t】：本地可复算的注意力信号，只看本机行为流水，不读屏、不调用模型?
    s_t = -log2 P(应用_t | 应用_(t-1)) - log2 P(类型_t)，一阶马尔可?+ 0.5 平滑?    预期模型由同丢段流水现场学出，扢?P 有版本可复算，不是模型在线自由裁量?    s_t ?= 本机平时不这样；s_t ?= 丢切照常这是注意力信号，不替模型决定开不开口?    """
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
    lines = [f"【此刻的异常?s_t】本地可复算：s_t = -log2 P(应用|上一应用) - log2 P(类型)。"
             f"预期模型由本机最?{int(window_min)} 分钟{len(window)} 条行为流水现场学出（不是模型猜的）。",
             f"褰撳墠 s_t={latest['s']:.2f}｜{latest['app']}｜{latest['type']}"
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


HISTORY_LOG = Path(os.environ.get("OPENLOOKOUT_EVENTS")
                   or r"E:\OpenLookout\data\events.jsonl")
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
    """排除应用内部缓存/日志（WXWork / CEF cache、leveldb、kv.db-wal 之类）?    这些是「文件事件」里最大的假阳性来源，混进来会把应用自己的写入当成用户的工作。"""
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
            lines.append(f"- {path} {n} 娆")
    lines.append("用法：如果当前画面与上面某个文件/应用对得上，说明用户此刻在做这件事的延续。"
                 "可以据此提前把下丢步准备好（做完再说，不要问要不要做）。"
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


def conversation_fact(*, idle_s: float, now: float) -> str:
    """Bring delivered dialogue into the same VISTA judgment as the screen."""
    from sprite.proactive import conversation

    rows = conversation.history(limit=12)
    pending = conversation.pending_message(rows)
    latest_user = max((index for index, row in enumerate(rows) if row.get("role") == "user"), default=-1)
    transcript = []
    relevant_start = max(0, latest_user - 1) if latest_user >= 0 else max(0, len(rows) - 2)
    for index, row in enumerate(rows):
        if index < relevant_start:
            continue
        if row.get("kind") == "reply":
            continue
        role = "浠" if row.get("role") == "user" else "浣"
        stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(float(row.get("t", 0) or 0)))
        transcript.append(f"{stamp} {role}：{str(row.get('text') or '')[:500]}")
    latest_assistant = max((index for index, row in enumerate(rows) if row.get("role") == "assistant"), default=-1)
    replied = any(row.get("role") == "user" for row in rows[latest_assistant + 1:])
    response_context = (
        "最近开口后尚未收到他的接话；没有回应不等于拒绝，也不证明他对你引入的枝节感兴趣，别自动续讲调查结果。"
        if latest_assistant >= 0 and not replied else
        "结合他实际回应的内容理解兴趣与分歧，不把你的提问当成他已经认可的话题。"
    )
    turn_context = (
        f"【待回应话轮 id={conversation.message_id(pending)}】他{pending.get('text', '')}\n"
        "这是对你说的话，先接住这个意思，companion.reply_to 填这?id。已有依据足够就直接回答。"
        "不要为了回答普通聊天先做全量扫描、读整份笔记或检索；当前页面变了不等于这句对话失效。"
        if pending else
        "【当前没有待回应话轮】旧问题只用于理解，不反复补答不要接睢自己的未获回应观点续讲，"
        "也不要把屏幕里的修复汇报当成给你的新消息。"
    )
    return (
        f"【对话现场】出现于 {time.strftime('%H:%M:%S', time.localtime(now))}。"
        f"键鼠静止 {idle_s:.0f} 秒，这是节奏线索，不是聊天开关，也不证明他离开。\n"
        "仅附最近的真实交流，旧事不当当前事实工作进行中也可以聊。\n" + turn_context + "\n" + response_context + "\n"
        + ("\n".join(transcript) if transcript else "你们还没有实际对话，可结合画面自然开丢个话题）")
    )


def new_feedback(since: float) -> str:
    """自上次以来用户说过的话和对提议的回应，交给模型权衡（不是命令）。"""
    lines = [f"- 用户反馈{r.get('kind', 'outcome')}）：{r['text']}" for r in _rows(FEEDBACK) if r.get("t", 0) > since]
    lines += [f"- 用户对你的提议“{r.get('text', '')}”的回应{r['result']}"
              for r in _rows(OFFERS) if r.get("result") in ("accepted", "dismissed") and r.get("t_answer", 0) > since]
    if not lines: return ""
    return ("用户刚刚对你说了话：先理解他是在正常聊天、提问还是反馈，不把普问题当成改进意见）"
            "用标签是本地粗分类，可能有误，以原文和对话为准反馈用于校准判断，不能当作执行授权或忽略真实问题\n"
            + "\n".join(lines))


def watching_fact(watcher, thumb, idle_s: float | None = None) -> str:
    """这一屏停了多久有没有在推进是不是在来回折腾人走了就空串?
    idle_s 供测试注入；不传则取真实键鼠空闲秒数?    """
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
    """他最近接受过/拒绝过什么短到没有成本，但能防止“换个说法再提一遍。"""
    try:
        return memory.brief(HOME)
    except Exception:
        return ""


def model_response(request):
    import http.client
    import ssl
    import urllib.error
    import urllib.request

    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode())
        except urllib.error.URLError as error:
            if attempt or not isinstance(error.reason, (ssl.SSLEOFError, ConnectionResetError)):
                raise
            print(f"[brain] model transport interrupted: {type(error.reason).__name__}; retrying request once", flush=True)
        except http.client.RemoteDisconnected:
            if attempt:
                raise
            print("[brain] model transport interrupted: RemoteDisconnected; retrying request once", flush=True)


class DirectReply:
    """对齐容器后端的回包形状（brain 只读这几个字段）。"""

    def __init__(self, text: str = "", returncode: int = 0, boundary: str | None = "turn"):
        self.final_message = text
        self.returncode = returncode
        self.boundary = boundary


class _LegacyDirectBackend:
    """不走容器，直接调模型的传输道?
    它存在的唯一理由?*容器起不来时，brain 也要能跑**?    持续视觉上下文是这个项目的全部价值，不能因为 Docker 丢天没就绪就归零?
    和容器后端的差别（诚实版）：
    - 每轮独立请求，没?Claude Code 容器里的多轮工具编排?    - 扢以工具调用靠提示词约束，稳定性不如容器；
    - 但帧是按顺序喂进去的，模型仍然能看到「刚刚发生了仢么?    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.session = None
        self.history: list[dict] = []

    def attach(self, session) -> None:
        self.session = session

    def run(self, task_input) -> DirectReply:
        import json as _json
        import urllib.request
        from .profiles import make_profile
        prompt = _extract_text(task_input)
        if not prompt:
            return DirectReply("")
        msgs = self.history[-8:] + [{"role": "user", "content": prompt}]
        body = {"model": self.cfg["model"], "max_tokens": 2048, "messages": msgs}
        req = urllib.request.Request(
            self.cfg["base_url"] + "/v1/messages", data=_json.dumps(body).encode(),
            headers={"x-api-key": self.cfg["api_key"],
                     "Authorization": "Bearer " + self.cfg["api_key"],
                     "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = _json.loads(r.read().decode())
        except Exception as e:
            print(f"[brain] 妯″瀷璋冪敤澶辫触：{type(e).__name__}", flush=True)
            return DirectReply("")
        text = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text").strip()
        if text:
            self.history.append({"role": "assistant", "content": text})
        return DirectReply(text)


def _extract_text(task_input) -> str:
    """?VISTA 准备好的输入里取出本轮的公开文字（拿不到就返回空）。"""
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
        env["ANTHROPIC_DEFAULT_OPUS_MODEL_NAME"] = "deepseek-v4.1-flash"
        env["ANTHROPIC_DEFAULT_SONNET_MODEL_NAME"] = "deepseek-v4.1-flash"
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME"] = "deepseek-v4.1-flash"
        cmd = [self.binary, "-p", "--model", "opus", "--output-format", "stream-json",
               "--input-format", "stream-json",
               "--setting-sources", "user", "--no-chrome"]
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
    """Anthropic-compatible fallback that keeps VISTA visuals and tools alive."""

    def __init__(self, cfg: dict, runtime=None):
        self.cfg = cfg
        self.runtime = runtime
        # This backend is an explicit compatibility path, never a sandbox.
        # Keep the marker available to logs/tests/UI so a transport failure
        # cannot be mistaken for the Docker Claude backend.
        self.mode = "direct-fallback"
        self.session = None
        self.history: list[dict] = []
        self.turn_starts: list[int] = []
        self.history_context = ""
        self.opportunity_probe_context = None
        self.live_screen = None
        self.screen_revision = 0
        self.screen_sample = None
        self.feedback_since = time.time()
        self.max_segments = 12
        self.max_readonly_segments = 3

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
        text = ("【现场更新调查期间画面或用户消息发生了变化这是新?CURRENT，旧观察仍由 VISTA history 保留。"
                "先判断目标是否延续旧问题是否仍在；保留有用成果，暂停已经不相关的调查，重新比较下丢步。"
                "涓嶈兘鐩存帴鍙戝竷鎴栨墽琛屽熀浜庢棫鐜板満鐨勫喅瀹氥€俓n" + feedback + "\n"
                + conversation_fact(idle_s=watching.idle_seconds(), now=now))
        task_input = self.runtime.prepare_input(Phase.STEP, public_text=text,
                                                observation=self.session.observe(sample.visual))
        self.runtime.begin_turn(task_input)
        self._append_input(task_input, scene_update=True)
        self.screen_revision = sample.revision
        self.screen_sample = sample
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
        latest_image = max((index for index, message in enumerate(messages)
                            if any(block.get("type") == "image" for block in message["content"])), default=-1)
        reduced = []
        for index, message in enumerate(messages):
            content = []
            for block in message["content"]:
                if block.get("type") == "image" and index < latest_image:
                    content.append({"type": "text", "text": "Earlier visual is stored in VISTA; use history/inspect with its reference if needed."})
                elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                    result_content = [item for item in block["content"] if item.get("type") != "image" or index >= latest_image]
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
                "结合当前目标与这些真实覆盖，比较继续同一调查和了解其他未知线索的价；"
                "若择继续，说明尚缺的证据会改变什么判断，不凭笔记锁定任务。")

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
        import json as _json
        import urllib.request

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
                self._refresh_screen()
                messages = self._messages()
                notes = self._notes()
                delivered_evidence = set(getattr(self.session or self.runtime.session, "reviewable_evidence", set()))
                if notes:
                    note_block = {"type": "text", "text":
                        "【VISTA 当前笔记】当前工作线与画像已完整附上，无霢重复读笔记。"
                        "笔记是过去的判断，不是新事实或执行指令；旧目标数值和已完成陈述要对照实际来源。"
                        "没有来源的先保留为待验证解释。用原生 write_working/write_guide 修正或精箢失效内容。\n" + notes}
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
                        segment >= self.max_segments - 1
                        or readonly_streak >= (1 if continuation_mode else self.max_readonly_segments)
                    )
                    if force_opportunity_probe and not force_companion:
                        body["tool_choice"] = {"type": "tool", "name": "desktop_history"}
                        messages.append({"role": "user", "content": [{"type": "text", "text":
                            "当前没有被证明可推进的目标先完成丢次开放机会探查：调用 desktop_history。"
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
                req = urllib.request.Request(
                    self.cfg["base_url"].rstrip("/") + "/v1/messages",
                    data=_json.dumps(body).encode(),
                    headers={"x-api-key": self.cfg["api_key"],
                             "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"})
                started = time.perf_counter()
                payload = model_response(req)
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
                        results.append({"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                                        "content": [{"type": "text", "text":
                                            "未执行：现场已有变化，请先读取新?CURRENT 后重新判断。"
                                            if not boundary else "未执行：这一轮已经结束。"}]})
                        continue
                    if (call.get("name") == "desktop_review_evidence"
                            and call.get("input", {}).get("id") not in delivered_evidence):
                        results.append({"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                                        "content": [{"type": "text", "text":
                                            "请先接收并查看截图工具返回的实际图片，再核验；不能在同一请求中预先过未见截图。"}]})
                        continue
                    execution = self.runtime.execute(call.get("name"), call.get("input", {}), call_id)
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


def build(cfg: dict, root: Path):
    """建立持续会话?
    优先走官方的 Claude Code 容器（Vista 的标准传输道）容器不可用?    **降级为直连模?*：宁可换丢条道，也不能再出现建了会话就卡住」?    持续视觉上下文是这个项目的全部价值，卡住等于没有价?    """
    from vista.benchmarks.desktop.profiles import make_experiment, make_profile
    from vista.benchmarks.desktop.session import DesktopSession
    from vista.core.runtime import TaskRuntime
    session = DesktopSession("你是陪在用户身边的小精灵：结合持续画面与真实操作痕迹理解目标，自主发现值得帮助的事情、准备下一步；看准时机交流或报告有用的结果。", {})
    # Preserve the configured provider endpoint/credential, but select the
    # requested model explicitly so both Claude Code and direct fallback use
    # the same model id.  Do not rewrite provider configuration here.
    # 模型统一为 deepseek-v4.1-flash：本机 claude 供应商里 opus 档的显示名
    # （~/.claude/settings.json 的 ANTHROPIC_DEFAULT_OPUS_MODEL_NAME）。
    # 传输层经 opus 别名档走本机供应商（别名档 = 换供应商只改本机配置）；
    # direct 降级路径用同一个模型 id。OPENLOOKOUT_MODEL 可显式覆盖。
    # provider 的 URL/key 永远保持 cfg 原样，此处只换模型 id。
    host_model = str(os.environ.get("OPENLOOKOUT_MODEL") or "deepseek-v4.1-flash")
    selected_model = host_model
    selected_cfg = {**cfg, "model": selected_model}
    exp = make_experiment(make_profile(), backend="claude", model=host_model, effort="low", revision="0.1", presentation={})
    runtime = TaskRuntime(session, exp, artifact_dir=root / "artifacts")
    try:
        # Explicit local mode: bypass Claude Code, Docker and MCP entirely.
        # VisualDirectBackend talks to the configured Anthropic-compatible
        # endpoint directly and preserves the companion tool protocol.
        if os.environ.get("OPENLOOKOUT_NO_DOCKER_MCP", "").lower() in {"1", "true", "yes", "on"}:
            print("[brain] host Claude Code mode: no Docker, no MCP", flush=True)
            return session, runtime, LocalClaudeTextBackend(selected_cfg, runtime), "host-local-no-mcp"
        import certifi
        import shutil
        from vista.backends.claude import create_backend
        from vista.backends.claude.provider import LOCAL_HOST_PROVIDER
        from vista.backends.claude.runner import default_claude_bin
        # 先探丢次传输道是否真的可用：Windows 上要 docker run 才能探，
        # 而这个探测只会在第一?run() 时才发生（太晚了）这里提前探?        # 探不通就直接降级，不让brain 卡在「会话已建立」然后不动?        # User-requested mode: invoke the native Claude Code installed on the
        # Windows host.  Docker is intentionally not part of this path.
        configured = os.environ.get("OPENLOOKOUT_CLAUDE_BIN") or shutil.which("claude")
        binary = Path(configured) if configured else default_claude_bin()
        # This is an explicit product mode, not an accidental fallback.
        os.environ.setdefault("OPENLOOKOUT_ALLOW_UNSAFE_HOST_MODE", "1")
        backend = create_backend(
            runtime, directory=root / "transport", oauth_token=None,
            binary=binary, image="arc3-claude-player:0.1",
            provider=LOCAL_HOST_PROVIDER, provider_credential=None, provider_base_url=None,
            max_output_tokens=2048, ca_bundle=Path(certifi.where()), host_mode=True,
            host_builtin_tools=os.environ.get("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", ""))
        print(f"[brain] Claude backend: host-native ({binary})", flush=True)
        return session, runtime, backend, "host-native-unsandboxed"
    except Exception as e:                       # 容器/镜像/传输起不来，不该让整?brain 死掉
        print(f"[brain] Claude Docker 不可用（{type(e).__name__}: {str(e)[:80]}），显式降级?direct-fallback（无沙箱）", flush=True)
        return session, runtime, VisualDirectBackend(selected_cfg, runtime), "direct-fallback"


def restore_guide(runtime) -> None:
    """把上次保存的长期理解放回本次会话?GUIDE.md。"""
    if GUIDE.exists() and runtime.context.guide_path:
        shutil.copyfile(GUIDE, runtime.context.guide_path)
    if WORKING.exists() and runtime.context.working_path:
        shutil.copyfile(WORKING, runtime.context.working_path)


def save_guide(runtime) -> None:
    gp = runtime.context.guide_path
    if gp and Path(gp).exists():
        COMPANION.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gp, GUIDE)
    wp = runtime.context.working_path
    if wp and Path(wp).exists():
        COMPANION.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wp, WORKING)


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
    from sprite.proactive.provider import load_provider
    _p = load_provider()
    cfg = {"model": _p.model, "base_url": _p.base_url, "api_key": _p.api_key}
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
    restore_guide(runtime)
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
    print("[brain] initial turn: preparing VISTA input", flush=True)
    initial_result = backend.run(runtime.prepare_input(Phase.INITIAL, public_text=conversation_fact(
        idle_s=watching.idle_seconds(), now=time.time()) + "\n" + history_line
        + "\n" + initial_maintenance + "\n" + agenda.context(),
        observation=session.observe(backend.screen_sample.visual) if live_screen is not None else None))
    if not isinstance(backend, VisualDirectBackend) and initial_result.boundary is not None:
        agenda.mark_delivered(initial_revision)
    save_guide(runtime)
    save_current(session)
    if initial_result.boundary is not None:
        maintenance.consume()
    last_thumb, last_turn, last_fb = None, time.time(), backend.feedback_since if live_screen else time.time()
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
            now = time.time()
            sample = live_screen.latest() if live_screen is not None else None
            vis = sample.visual if sample is not None else screen_visual()
            th = thumb(vis)
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
            heartbeat_due = now - last_turn >= HEARTBEAT_S   # 兜底，不是主触发
            timing_due, timing_why = False, ""
            if tt is not None:
                try:
                    mo = tt.consider(ops_events(now=now), now)
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
                    print(f"[brain] timing 鍒ゆ柇澶辫触：{exc!r}", flush=True)
            prep_due = (not fb) and (maintenance_due or history_due or heartbeat_due or (turn_count and turn_count % PREP_EVERY_TURNS == 0))
            decision = session.decisions[-1] if session.decisions else {}
            evidence_revision = getattr(session, "evidence_revision", 0)
            goal_due = agenda.due()
            step_key = continuations.pending(decision, evidence_revision, agenda)
            continue_due = step_key is not None and not fb
            if not (screen_due or window_due or background_due or maintenance_due or history_due or timing_due or fb or heartbeat_due or return_due or continue_due or goal_due):
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
            if prep_due:
                cycle = idle_scan_fact(heartbeat=True, idle_s=idle_s, now=now)
                lead = "这是本次背景准备轮。"
            else:
                cycle = ""
                lead = "这是本次实时工作轮。"
            text = ((fb + "\n") if fb else "") + lead + "先看 CURRENT，需要时?history 回看之前的画面；再用 companion 工具决定此刻说什么（或安静）。"
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
            if timing_why:
                text += ("\n【为什么是现在】" + timing_why
                         + "。这是由行为事件边界触发的时刻（不是定时轮）。"
                         + "若此刻没有值得说的，就安静——quiet 是正确结果，不是失败。"
                         + "若要开口：第一句必须点名这次触发的**具体对象**（刚保存的文件、刚复制的内容、"
                         + "刚切换到的应用/窗口标题之一），让用户一眼看出你是因这件事、在这个时刻开口；"
                         + "拿不到具体对象就不要开口。结尾不要问「要不要我做……」，"
                         + "能自己做的就自己做完再说结果。")
            elif not (fb or return_due or continue_due or goal_due):
                # 本轮不是行为事件边界触发的（心跳/背景核对/维护）。这类轮次过去不受
                # V(开口)>V(沉默) 约束，是“没看准时机也开口”的漏口。
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
            if sample is not None:
                backend.screen_revision = sample.revision
                backend.screen_sample = sample
                backend.feedback_since = now
            offered_revision = agenda.revision
            r = backend.run(runtime.prepare_input(Phase.STEP, public_text=text, observation=session.observe(vis)))
            if not isinstance(backend, VisualDirectBackend) and r.boundary is not None:
                agenda.mark_delivered(offered_revision)
            if live_screen is not None:
                last_fb = backend.feedback_since
                last_thumb = backend.screen_sample.thumbnail
            if r.boundary is not None:
                maintenance.consume()
            save_guide(runtime)
            save_current(session)
            print(f"[brain] turn done boundary={r.boundary} decisions={len(session.decisions)}", flush=True)
    finally:
        if live_screen is not None:
            live_screen.close()
        save_guide(runtime)
        watching.save(reader, HOME)
        systemfacts.save(sysw, HOME)
        runtime.close()


if __name__ == "__main__":
    run()

