"""灏忕簿鐏电殑澶ц剳锛氫竴涓暱鏈熻繍琛岀殑 VISTA 浼氳瘽銆?- 鍚屼竴涓ā鍨嬩細璇濇寔缁瓨鍦紱VISTA 淇濆瓨姣忎竴甯у師濮嬬敾闈紙瑙嗚璁板繂锛夛紝妯″瀷鐢?history / inspect 鍥炵湅銆?- 姣忔灞忓箷鏈夋槑鏄惧彉鍖栵紝灏变互 STEP 杞鍠傜粰鍚屼竴涓細璇濓紱妯″瀷鐢?companion 宸ュ叿鍐冲畾鈥滆璇?鎻愯/瀹夐潤鈥濄€?- GUIDE.md锛堝鐢ㄦ埛鐨勯暱鏈熺悊瑙ｏ級璺ㄩ噸鍚繚鐣欏湪 sprite_home/companion/GUIDE.md锛?  鐢ㄦ埛鐨勫弽棣堬紙濂界殑/涓嶇敤/绾犳锛変互鏂囧瓧杩藉姞杩涗笅涓€杞紝鍙綔涓烘潈琛′緷鎹紝涓嶆槸鍛戒护銆?- 涓婁笅鏂囧揩婊℃椂鐢?VISTA 鑷繁浜ゆ帴锛屼笉閲嶅紑浼氳瘽锛涜繘绋嬪穿婧冩墠閲嶅惎銆?python -m vista.benchmarks.desktop.brain
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
CHANGE_MIN = 0.01          # 灞忓箷缂╃暐鍥惧钩鍧囧樊寮傝秴杩?1% 灏遍噸鏂板垽鏂?MIN_GAP_S = 5              # 椤甸潰鍒囨崲鍚庡敖蹇窡涓婏紱鑺傛祦浜ょ粰妯″瀷鍒ゆ柇鍜岃緭鍑洪椄
HEARTBEAT_S = 900          # 鍏滃簳蹇冭烦锛氫富瑙﹀彂宸蹭氦缁?sprite/proactive/timing.py 鐨勪簨浠惰竟鐣岀畻娉?PREP_EVERY_TURNS = 24      # rotate one background scan even during a busy screen
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
    """璇昏褰曞櫒姝ｅ湪鍐欑殑鏂囦欢锛氬叡浜 + 瀹瑰繊琚埅鏂殑鍗婅锛涗换浣曞け璐ラ兘杩斿洖绌鸿〃锛屼笉褰卞搷澶ц剳銆。"""
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
        print(f"[brain] timing events 涓嶅彲鐢細{exc!r}", flush=True)
    if events:
        TIMING_CACHE["at"] = now
        TIMING_CACHE["events"] = events
    return TIMING_CACHE["events"]


def timing_tracker():
    """鎯版€у垱寤烘椂鏈鸿拷韪櫒锛涘鍏ュけ璐ラ€€鍖栨垚 None锛堝ぇ鑴戠収甯歌窇锛屽彧鏄洖鍒版棫鐨勫績璺宠Е鍙戯級銆?
    timing v2锛氭椂鏁堟寜銆屾垜浠涓€娆＄湅瑙佽繖鏉′簨浠躲€嶇殑鏃跺埢绠楋紝鑰屼笉鏄畠鑷О鍙戠敓鐨勬椂鍒烩€斺€?    璁板綍鍣ㄦ妸 focus 鍖洪棿鍐欏湪缁撴潫鏃跺嵈鐢ㄥ紑濮嬫椂鍒诲仛 ts锛屼笉杩欐牱鏀癸紝涓€涓垰鍒氭墠鍙鍔ㄧ殑杈圭晫浼氳绠楁垚杩囨湡銆?    """
    global TIMING_TRACKER
    if TIMING_TRACKER is None:
        try:
            from sprite.proactive.timing import Tracker as _T
            TIMING_TRACKER = _T()
        except Exception as exc:
            print(f"[brain] timing 涓嶅彲鐢紝鍥為€€鍒板績璺宠Е鍙戯細{exc!r}", flush=True)
            TIMING_TRACKER = False
    return TIMING_TRACKER or None


def residual_fact(*, window_min: float = 90.0, refresh_s: float = 5.0, now: float | None = None) -> str:
    """銆愭鍒荤殑寮傚父搴?s_t銆戯細鏈湴鍙绠楃殑娉ㄦ剰鍔涗俊鍙凤紝鍙湅鏈満琛屼负娴佹按锛屼笉璇诲睆銆佷笉璋冪敤妯″瀷銆?
    s_t = -log2 P(搴旂敤_t | 搴旂敤_(t-1)) - log2 P(绫诲瀷_t)锛屼竴闃堕┈灏斿彲澶?+ 0.5 骞虫粦锛?    棰勬湡妯″瀷鐢卞悓涓€娈垫祦姘寸幇鍦哄鍑猴紝鎵€浠?P 鏈夌増鏈€佸彲澶嶇畻锛屼笉鏄ā鍨嬪湪绾胯嚜鐢辫閲忋€?    s_t 楂?= 鏈満骞虫椂涓嶈繖鏍凤紱s_t 浣?= 涓€鍒囩収甯搞€傝繖鏄敞鎰忓姏淇″彿锛屼笉鏇挎ā鍨嬪喅瀹氬紑涓嶅紑鍙ｃ€?    """
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
    lines = [f"銆愭鍒荤殑寮傚父搴?s_t銆戞湰鍦板彲澶嶇畻锛歴_t = -log2 P(搴旂敤|涓婁竴搴旂敤) - log2 P(绫诲瀷)锛"
             f"棰勬湡妯″瀷鐢辨湰鏈烘渶杩?{int(window_min)} 鍒嗛挓銆亄len(window)} 鏉¤涓烘祦姘寸幇鍦哄鍑猴紙涓嶆槸妯″瀷鐚滅殑锛夈€",
             f"褰撳墠 s_t={latest['s']:.2f}锝渰latest['app']}锝渰latest['type']}"
             + (f"锝渰latest['title']}" if latest["title"] else "")]
    if interesting:
        lines.append("鏈€杩?45 鍒嗛挓鏈€涓嶅甯哥殑鏃跺埢锛堣秺楂樿秺涓嶅儚鏈満骞虫椂鐨勬牱瀛愶級锛")
        for event in interesting:
            stamp = time.strftime("%H:%M:%S", time.localtime(event["t"]))
            lines.append(f"- {stamp} s_t={event['s']:.2f}锝渰event['app']}锝渰event['type']}"
                         + (f"锝渰event['title']}" if event["title"] else ""))
    if since is not None:
        lines.append(f"璺濅笂涓€娆℃槑鏄惧紓甯哥害 {since / 60:.0f} 鍒嗛挓銆")
    lines.append("s_t 鍙槸缁熻淇″彿锛屼笉鏄粨璁猴細s_t 楂樿鏄庢鍒诲€煎緱鐪嬩竴鐪兼槸鍚︿笌鐢ㄦ埛褰撲笅鐩爣鏈夊叧锛"
                 "s_t 浣庝笉鑳芥帓闄ら噸澶嶅姵鍔ㄣ€佹湭瑙ｅ喅鐩爣鎴栬嚜鐒朵氦娴佹満浼氾紝浠嶉渶缁撳悎璇箟璇佹嵁鍒ゆ柇銆備笉瑕佷负浜嗘寚鏍囧紑鍙ｏ紝涔熶笉瑕佹妸鍒嗘暟蹇电粰鐢ㄦ埛銆")
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
    """鎺掗櫎搴旂敤鍐呴儴缂撳瓨/鏃ュ織锛圵XWork 鐨?CEF cache銆乴eveldb銆乲v.db-wal 涔嬬被锛夆€斺€?    杩欎簺鏄€屾枃浠朵簨浠躲€嶉噷鏈€澶х殑鍋囬槼鎬ф潵婧愶紝娣疯繘鏉ヤ細鎶婂簲鐢ㄨ嚜宸辩殑鍐欏叆褰撴垚鐢ㄦ埛鐨勫伐浣溿€?""
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
    """銆愰暱鏈熸ā寮忋€戯細浠庢暣鏈烘搷浣滃巻鍙诧紙涓嶆槸灏忕簿鐏佃嚜宸遍偅 90 绉掔獥鍙ｏ級閲岃繛缁劅鐭ャ€"
    杩欐槸銆屾寔缁富鍔ㄦ劅鐭ャ€嶇殑璁板繂閭ｄ竴鍗婏細鍙湅鏈満娴佹按銆佹湰鍦板彲澶嶇畻銆佷笉璇诲睆銆佷笉璋冩ā鍨嬨€?    缁欏嚭鏈€杩戝嚑澶╃殑鏃堕棿鍘诲悜涓庡弽澶嶆敼鍔ㄧ殑鏂囦欢鈥斺€斿畠浠槸鍒ゆ柇銆岀敤鎴风幇鍦ㄥ湪鍋氫粈涔堛€?    鍗″湪鍝€佸€间笉鍊煎緱甯€嶇殑鏈€寮洪敋鐐广€傛瘡 refresh_s 绉掗噸绠椾竴娆°€?    """
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
    lines = [f"銆愰暱鏈熸ā寮忋€戞暣鏈烘搷浣滃巻鍙诧紙涓嶆槸灏忕簿鐏佃嚜宸辩殑绐楀彛锛夛細鏈€杩?{days:.0f} 澶╄鍒?{kept} 鏉¤涓轰簨浠躲€?,
             "鏃堕棿鍘诲悜锛? + "銆?.join(f"{app} {n} 鏉? for app, n in top_apps)]
    if churn:
        lines.append("鍙嶅璇诲啓鐨勬枃浠讹紙闀挎湡鍦ㄦ墜锛屾槸鍒ゆ柇褰撲笅鐩爣鐨勬渶濂介敋鐐癸級锛?)
        for path, n in churn[:6]:
            lines.append(f"- {path} {n} 娆?)
    lines.append("鐢ㄦ硶锛氬鏋滃綋鍓嶇敾闈笌涓婇潰鏌愪釜鏂囦欢/搴旂敤瀵瑰緱涓婏紝璇存槑鐢ㄦ埛姝ゅ埢鍦ㄥ仛杩欎欢浜嬬殑寤剁画锛?
                 "鍙互鎹鎻愬墠鎶婁笅涓€姝ュ噯澶囧ソ锛堝仛瀹屽啀璇达紝涓嶈闂涓嶈鍋氾級銆?
                 "浣嗛暱鏈熸ā寮忎笉鏋勬垚鎵撴壈鐞嗙敱鈥斺€旀槸鍚﹀紑鍙ｄ粛鐢卞綋涓嬫椂鏈哄喅瀹氾紝瀹佸彲 quiet銆?)
    text = "\n".join(lines)
    LONG_TERM_CACHE.update(at=now, text=text)
    print(f"[brain] long-term days={days:.0f} events={kept} churn={len(churn)}", flush=True)
    return text


def idle_scan_fact(*, heartbeat: bool, idle_s: float, now: float) -> str:
    """Invite a goal-driven preparation decision without selecting a topic."""
    if not heartbeat:
        return ""
    if idle_s >= watching.DEFAULTS["away_s"]:
        mode = "閿紶闀挎椂闂存湭鍔細鍙兘鍦ㄩ槄璇绘垨绛夊緟锛屼篃鍙兘鏆傜锛岀粨鍚堣繛缁敾闈㈠垽鏂紝涓嶆妸鏃犳搷浣滅洿鎺ュ綋鎴愪汉宸茬寮€銆?
    else:
        mode = "缁撳悎杩炵画鐢婚潰鍒ゆ柇褰撳墠鑺傚锛氬彲浠ュ噯澶囦笅涓€姝ワ紝涔熷彲浠ヨ嚜鐒舵帴璇濓紱鏈疆骞朵笉瑕佹眰寮€鍙ｃ€?
    return (f"銆愯儗鏅噯澶囥€憑mode} 鎶婃搷浣滆褰曞彂鐜伴棶棰樸€佸悗鍙扮淮鎶ゅ拰鑷劧浜ゆ祦鏀捐繘鍚屼竴涓垽鏂細"
            "鍏堢湅鏄惁鏈夌敤鎴峰皻鏈В鍐崇殑闂锛屽啀鍐冲畾琛ヨ瘉鎹€佹帹杩涘府鍔┿€佺淮鎶ゃ€佽亰澶╂垨瀹夐潤锛涜嚜宸遍€夋嫨鏈€鍊煎緱缁х画鐨勪竴姝ワ紝涓嶆寜鍥哄畾涓婚杞浆銆?
            "quiet 鍙喅瀹氭槸鍚﹀紑鍙ｏ紝涓嶄唬琛ㄥ悗鍙板仠姝紱鏈煡璧勬枡鍙兘鍊煎緱涓€娆″皬鏌ヨ锛岀湡瀹炲繀椤荤瓑寰呮墠鍐?waiting銆?
            "涓嶈涓€娆℃€ф壂瀹屾暣鍘嗗彶锛屾部鍏蜂綋鍋囪閫愭琛ヨ瘉鎹€傛瘮杈冪户缁師鏂规銆佹崲鏂瑰悜銆佸噯澶囦笅涓€姝ュ拰绛夊緟鐨勬敹鐩婏紝"
            "鎶婇鏈熸敼鍠勩€侀獙璇佹柟寮忎笌缁撴灉鍐欒繘 WORKING.md锛岃€屼笉鏄负浜嗘湁浜嬪彲鍋氳€屽埗閫犱换鍔°€?
            "鍩虹鏈嶅姟鍜屽叕鍏辨绱㈠彧鍦ㄨ兘鏀瑰彉褰撳墠鍒ゆ柇鎴栨敼鍠勪氦娴佹椂浣跨敤锛屼笉鑷姩鏌ユ瘡鏃ュぉ姘斻€?)


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
        role = "浠? if row.get("role") == "user" else "浣?
        stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(float(row.get("t", 0) or 0)))
        transcript.append(f"{stamp} {role}锛歿str(row.get('text') or '')[:500]}")
    latest_assistant = max((index for index, row in enumerate(rows) if row.get("role") == "assistant"), default=-1)
    replied = any(row.get("role") == "user" for row in rows[latest_assistant + 1:])
    response_context = (
        "鏈€杩戝紑鍙ｅ悗灏氭湭鏀跺埌浠栫殑鎺ヨ瘽锛涙病鏈夊洖搴斾笉绛変簬鎷掔粷锛屼篃涓嶈瘉鏄庝粬瀵逛綘寮曞叆鐨勬灊鑺傛劅鍏磋叮锛屽埆鑷姩缁璋冩煡缁撴灉銆?
        if latest_assistant >= 0 and not replied else
        "缁撳悎浠栧疄闄呭洖搴旂殑鍐呭鐞嗚В鍏磋叮涓庡垎姝э紝涓嶆妸浣犵殑鎻愰棶褰撴垚浠栧凡缁忚鍙殑璇濋銆?
    )
    turn_context = (
        f"銆愬緟鍥炲簲璇濊疆 id={conversation.message_id(pending)}銆戜粬锛歿pending.get('text', '')}\n"
        "杩欐槸瀵逛綘璇寸殑璇濓紝鍏堟帴浣忚繖涓剰鎬濓紝companion.reply_to 濉繖涓?id銆傚凡鏈変緷鎹冻澶熷氨鐩存帴鍥炵瓟锛?
        "涓嶈涓轰簡鍥炵瓟鏅€氳亰澶╁厛鍋氬叏灞€鎵弿銆佽鏁翠唤绗旇鎴栨绱€傚綋鍓嶉〉闈㈠彉浜嗕笉绛変簬杩欏彞瀵硅瘽澶辨晥銆?
        if pending else
        "銆愬綋鍓嶆病鏈夊緟鍥炲簲璇濊疆銆戞棫闂鍙敤浜庣悊瑙ｏ紝涓嶅弽澶嶈ˉ绛斻€備笉瑕佹帴鐫€鑷繁鐨勬湭鑾峰洖搴旇鐐圭画璁诧紝"
        "涔熶笉瑕佹妸灞忓箷閲岀殑淇姹囨姤褰撴垚缁欎綘鐨勬柊娑堟伅銆?
    )
    return (
        f"銆愬璇濈幇鍦恒€戠幇鍦?{time.strftime('%H:%M:%S', time.localtime(now))}锛?
        f"閿紶闈欐 {idle_s:.0f} 绉掞紝杩欐槸鑺傚绾跨储锛屼笉鏄亰澶╁紑鍏筹紝涔熶笉璇佹槑浠栫寮€銆俓n"
        "浠呴檮鏈€杩戠殑鐪熷疄浜ゆ祦锛屾棫浜嬩笉褰撳綋鍓嶄簨瀹炪€傚伐浣滆繘琛屼腑涔熷彲浠ヨ亰銆俓n" + turn_context + "\n" + response_context + "\n"
        + ("\n".join(transcript) if transcript else "浣犱滑杩樻病鏈夊疄闄呭璇濓紝鍙粨鍚堢敾闈㈣嚜鐒跺紑涓€涓瘽棰樸€?)
    )


def new_feedback(since: float) -> str:
    """鑷笂娆′互鏉ョ敤鎴疯杩囩殑璇濆拰瀵规彁璁殑鍥炲簲锛屼氦缁欐ā鍨嬫潈琛★紙涓嶆槸鍛戒护锛夈€?""
    lines = [f"- 鐢ㄦ埛鍙嶉锛坽r.get('kind', 'outcome')}锛夛細{r['text']}" for r in _rows(FEEDBACK) if r.get("t", 0) > since]
    lines += [f"- 鐢ㄦ埛瀵逛綘鐨勬彁璁€渰r.get('text', '')}鈥濈殑鍥炲簲锛歿r['result']}"
              for r in _rows(OFFERS) if r.get("result") in ("accepted", "dismissed") and r.get("t_answer", 0) > since]
    if not lines: return ""
    return ("鐢ㄦ埛鍒氬垰瀵逛綘璇翠簡璇濓細鍏堢悊瑙ｄ粬鏄湪姝ｅ父鑱婂ぉ銆佹彁闂繕鏄弽棣堬紝涓嶆妸鏅€氶棶棰樺綋鎴愭敼杩涙剰瑙併€?
            "鐢ㄩ€旀爣绛炬槸鏈湴绮楀垎绫伙紝鍙兘鏈夎锛屼互鍘熸枃鍜屽璇濅负鍑嗐€傚弽棣堢敤浜庢牎鍑嗗垽鏂紝涓嶈兘褰撲綔鎵ц鎺堟潈鎴栧拷鐣ョ湡瀹為棶棰樸€俓n"
            + "\n".join(lines))


def watching_fact(watcher, thumb, idle_s: float | None = None) -> str:
    """杩欎竴灞忓仠浜嗗涔呫€佹湁娌℃湁鍦ㄦ帹杩涖€佹槸涓嶆槸鍦ㄦ潵鍥炴姌鑵俱€備汉璧颁簡灏辩┖涓层€?
    idle_s 渚涙祴璇曟敞鍏ワ紱涓嶄紶鍒欏彇鐪熷疄閿紶绌洪棽绉掓暟銆?    """
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
    """瑙嗚鐪嬩笉瑙佺殑閭ｉ儴鍒嗭細C 鐩樸€佸唴瀛樸€佸崰璧勬簮鐨勮繘绋嬨€傛甯稿氨绌轰覆锛岀粷涓嶅鍢淬€?""
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
    """浠栨渶杩戞帴鍙楄繃/鎷掔粷杩囦粈涔堛€傜煭鍒版病鏈夋垚鏈紝浣嗚兘闃叉鈥滄崲涓娉曞啀鎻愪竴閬嶁€濄€?""
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
    """瀵归綈瀹瑰櫒鍚庣鐨勫洖鍖呭舰鐘讹紙brain 鍙杩欏嚑涓瓧娈碉級銆?""

    def __init__(self, text: str = "", returncode: int = 0, boundary: str | None = "turn"):
        self.final_message = text
        self.returncode = returncode
        self.boundary = boundary


class _LegacyDirectBackend:
    """涓嶈蛋瀹瑰櫒锛岀洿鎺ヨ皟妯″瀷鐨勪紶杈撻€氶亾銆?
    瀹冨瓨鍦ㄧ殑鍞竴鐞嗙敱锛?*瀹瑰櫒璧蜂笉鏉ユ椂锛宐rain 涔熻鑳借窇**銆?    鎸佺画瑙嗚涓婁笅鏂囨槸杩欎釜椤圭洰鐨勫叏閮ㄤ环鍊硷紝涓嶈兘鍥犱负 Docker 涓€澶╂病灏辩华灏卞綊闆躲€?
    鍜屽鍣ㄥ悗绔殑宸埆锛堣瘹瀹炵増锛夛細
    - 姣忚疆鐙珛璇锋眰锛屾病鏈?Claude Code 瀹瑰櫒閲岀殑澶氳疆宸ュ叿缂栨帓锛?    - 鎵€浠ュ伐鍏疯皟鐢ㄩ潬鎻愮ず璇嶇害鏉燂紝绋冲畾鎬т笉濡傚鍣紱
    - 浣嗗抚鏄寜椤哄簭鍠傝繘鍘荤殑锛屾ā鍨嬩粛鐒惰兘鐪嬪埌銆屽垰鍒氬彂鐢熶簡浠€涔堛€嶃€?    """

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
            print(f"[brain] 妯″瀷璋冪敤澶辫触锛歿type(e).__name__}", flush=True)
            return DirectReply("")
        text = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text").strip()
        if text:
            self.history.append({"role": "assistant", "content": text})
        return DirectReply(text)


def _extract_text(task_input) -> str:
    """浠?VISTA 鍑嗗濂界殑杈撳叆閲屽彇鍑烘湰杞殑鍏紑鏂囧瓧锛堟嬁涓嶅埌灏辫繑鍥炵┖锛夈€?""
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
        text = ("銆愮幇鍦烘洿鏂般€戣皟鏌ユ湡闂寸敾闈㈡垨鐢ㄦ埛娑堟伅鍙戠敓浜嗗彉鍖栥€傝繖鏄柊鐨?CURRENT锛屾棫瑙傚療浠嶇敱 VISTA history 淇濈暀銆?
                "鍏堝垽鏂洰鏍囨槸鍚﹀欢缁€佹棫闂鏄惁浠嶅湪锛涗繚鐣欐湁鐢ㄦ垚鏋滐紝鏆傚仠宸茬粡涓嶇浉鍏崇殑璋冩煡锛岄噸鏂版瘮杈冧笅涓€姝ャ€?
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
        return ("銆愭湰娆′細璇濆疄闄呭彇璇佽鐩栥€戞潵鑷凡杩斿洖宸ュ叿缁撴灉锛屼笉閲囩敤绗旇涓殑鑷堪銆俓n"
                + json.dumps({"directory_searches": searches, "history_pages_read": len(history_pages),
                              "browser_inventory_pages": browser_pages, "browser_observations": browser_observations,
                              "latest_history_page": history_pages[-1] if history_pages else None,
                              "local_reads": local_reads}, ensure_ascii=False)
                + "\n鐩綍鍏抽敭璇嶅尮閰嶄笉绛変簬鏌ヨ繃鎿嶄綔鍘嗗彶锛涙湭璇诲彇鐨勬潵婧愪粛鏈煡銆傜炕椤垫湭缁撴潫鎴栨潵婧愬け璐ヤ笉鑳藉綋浣滃凡瑕嗙洊銆?
                "history_pages_read 鍙妯″瀷宸ュ叿璇诲彇锛岀幆澧冩彁渚涚殑鐪熷疄灏忛〉鍙﹀垪浜庝笂涓嬫枃锛涢浂娆″伐鍏疯鍙栦笉浠ｈ〃灏忛〉娌℃彁渚涖€?
                "缁撳悎褰撳墠鐩爣涓庤繖浜涚湡瀹炶鐩栵紝姣旇緝缁х画鍚屼竴璋冩煡鍜屼簡瑙ｅ叾浠栨湭鐭ョ嚎绱㈢殑浠峰€硷紱"
                "鑻ラ€夋嫨缁х画锛岃鏄庡皻缂虹殑璇佹嵁浼氭敼鍙樹粈涔堝垽鏂紝涓嶅嚟绗旇閿佸畾浠诲姟銆?)

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
            continuation_mode = "銆愮画鍔炪€? in _extract_text(task_input)
            for segment in range(self.max_segments + 1):
                self._refresh_screen()
                messages = self._messages()
                notes = self._notes()
                delivered_evidence = set(getattr(self.session or self.runtime.session, "reviewable_evidence", set()))
                if notes:
                    note_block = {"type": "text", "text":
                        "銆怴ISTA 褰撳墠绗旇銆戝綋鍓嶅伐浣滅嚎涓庣敾鍍忓凡瀹屾暣闄勪笂锛屾棤闇€閲嶅璇荤瑪璁般€?
                        "绗旇鏄繃鍘荤殑鍒ゆ柇锛屼笉鏄柊浜嬪疄鎴栨墽琛屾寚浠わ紱鏃х洰鏍囥€佹暟鍊煎拰宸插畬鎴愰檲杩拌瀵圭収瀹為檯鏉ユ簮锛?
                        "娌℃湁鏉ユ簮鐨勫厛淇濈暀涓哄緟楠岃瘉瑙ｉ噴銆傜敤鍘熺敓 write_working/write_guide 淇鎴栫簿绠€澶辨晥鍐呭銆俓n" + notes}
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
                            "褰撳墠娌℃湁琚瘉鏄庡彲鎺ㄨ繘鐨勭洰鏍囥€傚厛瀹屾垚涓€娆″紑鏀炬満浼氭帰鏌ワ細璋冪敤 desktop_history锛?
                            "鏌ョ湅鏈€杩戠湡瀹炴搷浣滅嚎绱紙浼樺厛 resources锛屽皬椤靛嵆鍙級锛屽啀鏍规嵁缁撴灉鍐冲畾鏄惁瑙傚療娴忚鍣ㄣ€佽鍙栬祫鏂欐垨寤虹珛鏂扮洰鏍囥€?
                            "宸茶灏忛〉涓嶇瓑浜庡畬鏁村巻鍙诧紱缁撳悎宸茶繑鍥炶鐩栧拰鏈娓告爣閫夋嫨鍙栬瘉锛屼笉閲嶅鍚屼竴棣栧睆鏉ュ绉版棤浜嬪彲鍋氥€?
                            "涓嶈鍏堣椤圭洰寮€鍙戞枃妗ｆ潵浠ｆ浛鐢ㄦ埛鍘嗗彶銆?}]})
                        opportunity_probe_used = True
                    else:
                        body["tool_choice"] = (
                            {"type": "tool", "name": "companion"}
                            if force_companion else {"type": "any"}
                        )
                    if force_companion:
                        messages.append({"role": "user", "content": [{"type": "text", "text":
                            "鏈疆鍗冲皢鍒拌揪浼犺緭涓婇檺锛屾垨杩炵画璋冩煡/澶辫触鍔ㄤ綔娌℃湁鏂板鍙敤璇佹嵁銆?
                            "鐜板湪璋冪敤 companion 淇濆瓨杩涘睍涓庝笅涓€姝ワ紱鍚庡彴闃舵鍙互 quiet锛屼笉瑕佹眰寮€鍙ｃ€?
                            "濉啓 next_step锛坮eady=涓€涓叿浣撳悗缁姩浣滐紝waiting=鏄庣‘缂轰粈涔堬紝done=宸插畬鎴愶級銆?
                            "涓嶈鍐嶈皟鐢ㄦ悳绱€佽绗旇鎴?history锛屼篃涓嶈鍙緭鍑烘枃瀛椼€?}]})
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
                        block.get("text", "").count("銆愭墽琛岃繘搴︼紝涓嶆槸鎺㈢储鏂瑰悜銆?)
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
                        "鏈疆娌℃湁鏀跺埌宸ュ叿璋冪敤銆備笉瑕佺户缁啓鍒嗘瀽锛涚珛鍗宠皟鐢?companion锛氱洿鎺ュ洖绛斿緟鍥炲簲娑堟伅锛?
                        "鎴栫敤 quiet 鏀跺熬骞跺～鍐?next_step銆備笉瑕佸啀璋冪敤 read_guide/read_working锛屽綋鍓嶇瑪璁板凡闄勪笂銆?}]})
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
                                            "鏈墽琛岋細鐜板満宸叉湁鍙樺寲锛岃鍏堣鍙栨柊鐨?CURRENT 鍚庨噸鏂板垽鏂€?
                                            if not boundary else "鏈墽琛岋細杩欎竴杞凡缁忕粨鏉熴€?}]})
                        continue
                    if (call.get("name") == "desktop_review_evidence"
                            and call.get("input", {}).get("id") not in delivered_evidence):
                        results.append({"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                                        "content": [{"type": "text", "text":
                                            "璇峰厛鎺ユ敹骞舵煡鐪嬫埅鍥惧伐鍏疯繑鍥炵殑瀹為檯鍥剧墖锛屽啀鏍搁獙锛涗笉鑳藉湪鍚屼竴璇锋眰涓鍏堥€氳繃鏈鎴浘銆?}]})
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
                            "杩欎釜宸ュ叿鏈彁渚涳紝涓嶈兘鎵ц銆傚疄闄呭彲鐢ㄥ伐鍏凤細" + ", ".join(tool["name"] for tool in tools)
                            + "銆傜敤瀹為檯宸ュ叿琛ヨ瘉鎹紱鑳藉姏缂哄彛濡傚疄淇濈暀锛屼笉鑳界寽宸ュ叿鍚嶅綋浣滆鍔ㄣ€?})
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
    """寤虹珛鎸佺画浼氳瘽銆?
    浼樺厛璧板畼鏂圭殑 Claude Code 瀹瑰櫒锛圴ista 鐨勬爣鍑嗕紶杈撻€氶亾锛夈€傚鍣ㄤ笉鍙敤鏃?    **闄嶇骇涓虹洿杩炴ā鍨?*锛氬畞鍙崲涓€鏉￠€氶亾锛屼篃涓嶈兘鍐嶅嚭鐜般€屽缓浜嗕細璇濆氨鍗′綇銆嶁€斺€?    鎸佺画瑙嗚涓婁笅鏂囨槸杩欎釜椤圭洰鐨勫叏閮ㄤ环鍊硷紝鍗′綇绛変簬娌℃湁浠峰€笺€?    """
    from vista.benchmarks.desktop.profiles import make_experiment, make_profile
    from vista.benchmarks.desktop.session import DesktopSession
    from vista.core.runtime import TaskRuntime
    session = DesktopSession("浣犳槸闄湪鐢ㄦ埛韬竟鐨勫皬绮剧伒锛氱粨鍚堟寔缁敾闈笌鐪熷疄鎿嶄綔鐥曡抗鐞嗚В鐩爣锛岃嚜涓诲彂鐜板€煎緱甯姪鐨勪簨鎯呫€佸噯澶囦笅涓€姝ワ紱鐪嬪噯鏃舵満浜ゆ祦鎴栨姤鍛婃湁鐢ㄧ殑缁撴灉銆?, {})
    # Preserve the configured provider endpoint/credential, but select the
    # requested model explicitly so both Claude Code and direct fallback use
    # the same model id.  Do not rewrite provider configuration here.
    # 妯″瀷缁熶竴閫?deepseek-v4.1-flash锛氭湰鏈?claude 渚涘簲鍟嗛噷 opus 妗ｇ殑鏄剧ず鍚?    # 锛垀/.claude/settings.json 鐨?ANTHROPIC_DEFAULT_OPUS_MODEL_NAME锛夈€?    # 浼犺緭灞傜粡 opus 鍒悕妗ｈ蛋鏈満渚涘簲鍟嗭紙鍒悕妗?= 鎹緵搴斿晢鍙敼鏈満閰嶇疆锛夛紱
    # direct 闄嶇骇璺緞鐢ㄥ悓涓€涓ā鍨?id銆侽PENLOOKOUT_MODEL 鍙樉寮忚鐩栥€?    # provider 鐨?URL/key 姘歌繙淇濇寔 cfg 鍘熸牱锛屾澶勫彧鎹㈡ā鍨?id銆?    host_model = str(os.environ.get("OPENLOOKOUT_MODEL") or "deepseek-v4.1-flash")
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
        # 鍏堟帰涓€娆′紶杈撻€氶亾鏄惁鐪熺殑鍙敤锛歐indows 涓婅 docker run 鎵嶈兘鎺紝
        # 鑰岃繖涓帰娴嬪彧浼氬湪绗竴娆?run() 鏃舵墠鍙戠敓锛堝お鏅氫簡锛夈€傝繖閲屾彁鍓嶆帰锛?        # 鎺笉閫氬氨鐩存帴闄嶇骇锛屼笉璁゜rain 鍗″湪銆屼細璇濆凡寤虹珛銆嶇劧鍚庝笉鍔ㄣ€?        # User-requested mode: invoke the native Claude Code installed on the
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
    except Exception as e:                       # 瀹瑰櫒/闀滃儚/浼犺緭璧蜂笉鏉ワ紝涓嶈璁╂暣涓?brain 姝绘帀
        print(f"[brain] Claude Docker 涓嶅彲鐢紙{type(e).__name__}: {str(e)[:80]}锛夛紝鏄惧紡闄嶇骇涓?direct-fallback锛堟棤娌欑锛?, flush=True)
        return session, runtime, VisualDirectBackend(selected_cfg, runtime), "direct-fallback"


def restore_guide(runtime) -> None:
    """鎶婁笂娆′繚瀛樼殑闀挎湡鐞嗚В鏀惧洖鏈浼氳瘽鐨?GUIDE.md銆?""
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
    row = {"t": time.time(), "activity": "姝ｅ湪閲嶆柊鐪嬪綋鍓嶇敾闈?, "state": "鏂颁細璇濆凡鍚姩锛屾鍦ㄥ缓绔嬭繛缁笂涓嬫枃", "source": "vista"}
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
    print(f"[brain] 浼氳瘽宸插缓绔嬶紙{mode}閫氶亾锛夛細鎸佺画瑙嗚涓婁笅鏂囧紑濮?, flush=True)
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
            heartbeat_due = now - last_turn >= HEARTBEAT_S   # 鍏滃簳锛屼笉鏄富瑙﹀彂
            timing_due, timing_why = False, ""
            if tt is not None:
                try:
                    mo = tt.consider(ops_events(now=now), now)
                    if mo.fire:
                        # 鎶娿€岃Е鍙戠殑鍏蜂綋瀵硅薄銆嶄竴骞朵氦缁欐ā鍨嬶紝鍚﹀垯瀹冨彧鑳芥硾娉涜€岃皥锛堣 GUIDE.md銆屽埆鍋氭寚鏍囪Е鍙戙€嶏級
                        try:
                            _d = mo.detail or {}
                            _bits = [str(v).strip() for v in (
                                _d.get("trigger_app"), _d.get("trigger_type"), _d.get("trigger_title")) if v]
                            _anchor = "/".join(_bits)
                            if _anchor or mo.key:
                                timing_why_extra = f"锛堣Е鍙戝璞★細{_anchor or '鏈煡'}锛岄敭 {mo.key}锛?
                            else:
                                timing_why_extra = ""
                        except Exception:
                            timing_why_extra = ""
                        timing_due, timing_why = True, mo.why + timing_why_extra
                        print(f"[brain] timing fire kind={mo.kind} V={mo.score:.3f} {mo.why} "
                              f"key={mo.key} anchor={timing_why_extra}", flush=True)
                    try:
                        # 鍙拌处璁板綍銆岀姸鎬佸彉鍖栥€嶏紝涓嶆槸瀹氭椂杞锛歠ire 鏃跺啓锛屾垨鍒ゅ畾绉嶇被鍙樹簡鏃跺啓涓€娆?                        if mo.fire or mo.kind != TIMING_CACHE.get("verdict_kind"):
                            TIMING_CACHE["verdict_kind"] = mo.kind
                            with open(PERCEIVE / "timing.jsonl", "a", encoding="utf-8") as fh:
                                fh.write(json.dumps({"t": now, **mo.to_dict()},
                                                    ensure_ascii=False) + "\n")
                    except OSError:
                        pass
                except Exception as exc:
                    print(f"[brain] timing 鍒ゆ柇澶辫触锛歿exc!r}", flush=True)
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
                lead = "杩欐槸涓€娆¤儗鏅噯澶囪疆銆?
            else:
                cycle = ""
                lead = "杩欐槸涓€娆″疄鏃跺伐浣滆疆銆?
            text = ((fb + "\n") if fb else "") + lead + "鍏堢湅 CURRENT锛岄渶瑕佹椂鐢?history 鍥炵湅涔嬪墠鐨勭敾闈紱鍐嶇敤 companion 宸ュ叿鍐冲畾姝ゅ埢璇翠粈涔堬紙鎴栧畨闈欙級銆?
            if continue_due:
                text += "\n銆愮画鍔炪€戣繖鏄綘閫夋嫨鐨勫彲缁х画涓嬩竴姝ワ紝涓嶇瓑寰呴〉闈㈠彉鍖栨垨鐢ㄦ埛寮€鍙ｏ細" + json.dumps(
                    continuations.step, sort_keys=True, ensure_ascii=False)
                text += "銆傚厛鎺ㄨ繘骞舵牳瀵圭粨鏋滐紝鍐嶆牴鎹柊澧炶瘉鎹喅瀹氱户缁€佹敼杩涙垨鎹㈡柟鍚戙€傚畨闈欏噯澶囦篃搴旀帹杩涳紱鍙湁宸ュ叿鏃犳硶鑷鍙栧緱鐨勫閮ㄦ潯浠舵墠绛夊緟銆?
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

