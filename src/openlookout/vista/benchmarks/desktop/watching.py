"""持续观察的计时事实：这一屏停了多久、有没有在推进、是不是在来回折腾、刚完成什么、人走没走。

分工（AGENTS.md 的核心原则）：
- **画面里是什么、该说什么**：VISTA 的持续视觉上下文负责。每一帧都在它的记忆里，
  模型用 history 回看、用 inspect 放大，认出用户在读书、写报告、修电脑还是看视频。
- **“多久 / 卡没卡 / 刚发生了什么”这类时间问题**：这个模块负责。每轮都从原始帧重新算一遍
  既贵又不可靠（模型数不准分钟数），所以它跟着会话一路记下来，brain 把 line() 附在 STEP 后面。

所以这里**没有任何场景白名单**——不认 Kindle、不认 PDF、不认浏览器。换什么场景都不用改代码：
用户是在读第 38 页还是盯着报错窗口，对“停了 6 分钟”这件事没有区别。
宁可安静：line() 只在该说话的时候才给内容，其余时候返回空串（= 没有值得注意的变化）。
"""
from __future__ import annotations

import ctypes, json, os, time
from ctypes import wintypes as W
from pathlib import Path

# 判定门槛。改这里等于改“什么情况算卡住/算做完一件事/人走了”。都偏保守，宁可漏报。
DEFAULTS = dict(stuck_s=180.0,        # 同一屏停这么久、人还在，算“卡住了/在想”
                flap_s=180.0,         # 这么久内回到刚才那一屏，算“来回翻/反复试”
                phase_s=120.0,        # 上一屏稳定这么久之后才变，算“一个阶段刚做完”
                progress_window_s=1200.0,   # 这个窗口里换屏次数用于判断“顺不顺”
                away_s=300.0,         # 用户无输入这么久算“离开了”
                keep_s=3600.0)        # 状态历史保留多久（再老的指纹不参与来回判定）


def _key(thumb, title: str) -> str:
    """一屏的身份：画面指纹（标题也参与，标题变了多半就是换了东西）。"""
    if not thumb: return f"title:{(title or '').strip()[:80]}"
    return f"{len(thumb)}:{sum(x * (i + 1) for i, x in enumerate(thumb)) % 1000003}:{(title or '').strip()[:40]}"


def _mins(s) -> str:
    if s is None: return ""
    s = max(0.0, float(s))
    return f"{int(s // 60)} 分钟" if s >= 90 else f"{int(s)} 秒"


class Watcher:
    """一轮一次 observe()，维护当前这一屏的时间事实。clock 注入便于测试。"""

    def __init__(self, cfg: dict | None = None, clock=time.time):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.clock = clock
        self.trail: list[dict] = []
        self.proc = ""
        self.title = ""
        self.key = ""; self.since = None
        self.hist: list[tuple[float, str]] = []      # (t, key) 最近的状态变化
        self.flaps = 0; self.phase = ""              # 刚结束的那个阶段（描述文字由 brain 填）
        self.prev2 = ""                              # 上一次变化之前那一屏：用来看 A→B→A
        self.last_change_t = None; self.idle_since = None; self.first_t = None
        self._phase_t = None                         # phase 是一次性事件：只在刚发生那一轮为真

    # ---------------------------------------------------------------- 序列化（brain 每轮存，重启接着算）
    def to_dict(self) -> dict:
        return dict(key=self.key, since=self.since, hist=self.hist, flaps=self.flaps, phase=self.phase,
                    prev2=self.prev2, last_change_t=self.last_change_t, idle_since=self.idle_since,
                    first_t=self.first_t, phase_t=self._phase_t, cfg=self.cfg,
                    trail=self.trail, proc=self.proc, title=self.title)

    @classmethod
    def from_dict(cls, d: dict) -> "Watcher":
        w = cls(cfg=d.get("cfg"))
        w.key = d.get("key", ""); w.since = d.get("since"); w.hist = [tuple(x) for x in d.get("hist", [])]
        w.flaps = int(d.get("flaps", 0)); w.phase = d.get("phase", ""); w.prev2 = d.get("prev2", "")
        w.last_change_t = d.get("last_change_t"); w.idle_since = d.get("idle_since"); w.first_t = d.get("first_t")
        w._phase_t = d.get("phase_t")
        w.trail = [dict(x) for x in d.get("trail", []) if isinstance(x, dict)][-24:]
        w.proc = str(d.get("proc", ""))[:48]
        w.title = str(d.get("title", ""))[:96]
        return w

    # ---------------------------------------------------------------- 主入口
    def observe(self, thumb, title: str = "", idle_s: float = 0.0, now: float | None = None,
                proc: str = "") -> "Watching":
        t = now if now is not None else self.clock()
        k = _key(thumb, title)
        proc, title = str(proc or "")[:48], str(title or "")[:96]
        if not self.key:                            # 第一次观察：只建立基线，不构成任何事件（还没有证据）
            self.key, self.since, self.last_change_t, self.first_t = k, t, t, self.first_t or t
            self.proc, self.title = proc, title
            return self.state(t)
        # 人走了：只记“走了多久”，不把静止误判成卡住
        if idle_s >= self.cfg["away_s"]:
            if self.idle_since is None: self.idle_since = t
            return self.state(t, away=True)
        self.idle_since = None
        if k != self.key:
            prev_key, prev_since = self.key, self.since
            if prev_since is not None:
                self.trail.append({"t": round(t, 3), "proc": self.proc,
                                   "title": self.title,
                                   "dwell_s": round(max(0.0, t - prev_since), 1)})
                self.trail = self.trail[-24:]
            if prev_since is not None and t - prev_since >= self.cfg["phase_s"]:
                self.phase = "阶段完成"            # 上一屏稳了很久才变：多半刚做完一件事
                self._phase_t = t                  # 记下发生的时刻，只播报一次
            if k == self.prev2 and prev_since is not None and t - prev_since <= self.cfg["flap_s"]:
                self.flaps += 1                    # A→B→A：又回到刚才那一屏（反复看/反复试）
            self.prev2 = prev_key
            self.key, self.since, self.last_change_t = k, t, t
            self.proc, self.title = proc, title
        self.hist = ([h for h in self.hist if t - h[0] <= self.cfg["keep_s"]] + [(t, k)])[-32:]
        return self.state(t)

    # ---------------------------------------------------------------- 事实
    @property
    def activity_line(self) -> str:
        """Compact recent foreground trail for strategic reasoning.

        The trail is intentionally emitted separately from the interruption
        facts in ``Watching.line()`` so smooth work remains quiet while the
        model can still discover repeated switching, abandoned windows, and
        long dormant tasks.
        """
        if not self.trail and not self.title:
            return ""
        rows = []
        for item in self.trail[-8:]:
            proc = item.get("proc") or "unknown"
            title = item.get("title") or "(untitled)"
            dwell = float(item.get("dwell_s") or 0)
            if dwell >= 90:
                duration = f"{int(dwell // 60)}m"
            else:
                duration = f"{int(dwell)}s"
            rows.append(f"{proc}: {title} ({duration})")
        if self.title:
            dwell = max(0.0, self.clock() - self.since) if self.since is not None else 0.0
            duration = f"{int(dwell // 60)}m" if dwell >= 90 else f"{int(dwell)}s"
            rows.append(f"当前 {self.proc or 'unknown'}: {self.title} ({duration})")
        return "【行为轨迹】最近窗口停留/切换：" + " → ".join(rows)

    @property
    def changes_in_window(self) -> int:
        return len({k for _, k in self.hist}) - 1 if len(self.hist) > 1 else 0

    @property
    def pattern_line(self) -> str:
        """Expose repeated waiting as evidence for strategic reasoning.

        The signal stays generic: the model decides what the workflow means
        from the visual context, while this module only supplies repeated
        dwell samples and a reminder to gather outcomes before interrupting.
        """
        rows = [r for r in self.trail[-16:] if float(r.get("dwell_s") or 0) >= 30]
        groups: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            key = (str(row.get("proc") or ""), str(row.get("title") or ""))
            groups.setdefault(key, []).append(float(row.get("dwell_s") or 0))
        candidates = [(key, values) for key, values in groups.items() if len(values) >= 3]
        if not candidates:
            return ""
        key, values = max(candidates, key=lambda item: (len(item[1]), sum(item[1])))
        title = key[1] or key[0] or "同一工作阶段"
        avg = sum(values) / len(values)
        low, high = min(values), max(values)

        def fmt(seconds: float) -> str:
            return f"{int(seconds // 60)}分钟" if seconds >= 90 else f"{int(seconds)}秒"

        return (f"【规律线索】“{title[:48]}”最近重复出现 {len(values)} 次，"
                f"每次停留约 {fmt(low)}-{fmt(high)}（平均 {fmt(avg)}）；"
                "这是待验证的流程耗时样本，继续收集成功/失败和时间段，寻找能减少等待的时机或准备动作，别仅凭一次样本打扰。")

    @property
    def stuck_s(self) -> float | None:
        if self.since is None: return None
        return self.clock() - self.since

    def state(self, t: float, away: bool = False) -> "Watching":
        same = (t - self.since) if self.since is not None else None
        own = self
        return Watching(
            watching_s=(t - self.first_t) if self.first_t else None,
            same_s=same, changes=self.changes_in_window, flaps=self.flaps,
            # phase 只在刚发生那一轮为真：否则同一句「刚做完一个阶段」会每轮重复播报
            phase=bool(self.phase) and self._phase_t is not None and (t - self._phase_t) < own.cfg.get("phase_report_s", 60.0),
            stuck=(same is not None and same >= own.cfg["stuck_s"] and not away),
            away=away, away_s=(t - own.idle_since) if (away and own.idle_since) else None,
            progressing=own.changes_in_window >= 3,
        )


class Watching:
    __slots__ = ("watching_s", "same_s", "changes", "flaps", "phase", "stuck", "away", "away_s", "progressing")

    DEF = dict(watching_s=None, same_s=0.0, changes=0, flaps=0, phase=False, stuck=False,
               away=False, away_s=None, progressing=False)

    def __init__(self, **kw):
        d = {**self.DEF, **kw}
        for k in self.__slots__: setattr(self, k, d[k])

    def line(self) -> str:
        """附在 STEP 后面的一句事实。没什么值得注意的就返回空串（= 安静陪着，别出声）。"""
        if self.away:
            return f"【观察】用户已经 {_mins(self.away_s)}没操作电脑了。别打扰，回来再说。"
        parts = []
        if self.same_s and self.same_s >= 60 and self.stuck:
            parts.append(f"这一屏停了 {_mins(self.same_s)}没变化")
        if self.stuck: parts.append("像是卡住了/在想")
        if self.flaps: parts.append(f"来回回到刚才那一屏 {self.flaps} 次（多半在反复看/反复试）")
        if self.phase: parts.append("上一屏稳了很久刚变——可能刚做完一个阶段")
        if self.progressing: pass                                    # 顺利推进本身就是理由：不说话
        if not parts: return ""                       # 顺手推进中：安静陪伴，什么都不必说
        return "【观察】" + "；".join(parts) + "。"


# ---------------------------------------------------------------- 取信号（Windows 前台窗口；拿不到就空）
def foreground() -> dict:
    """当前前台窗口的 (proc, title, pid)。失败/非 Windows 返回空事实，绝不猜。"""
    out = {"proc": "", "title": "", "pid": 0}
    if os.name != "nt": return out
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd: return out
        n = u.GetWindowTextLengthW(hwnd); buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1); pid = W.DWORD(); u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ""
        try:
            import psutil; name = psutil.Process(pid.value).name() if pid.value else ""
        except Exception: name = ""
        return {"proc": name, "title": buf.value, "pid": pid.value}
    except Exception: return out


def idle_seconds() -> float:
    """距上次键鼠输入多少秒（判断人走没走）。拿不到返回 0（当人在）。"""
    if os.name != "nt": return 0.0
    try:
        class LI(ctypes.Structure):
            _fields_ = [("cbSize", W.UINT), ("dwTime", W.UINT)]
        info = LI(ctypes.sizeof(LI), 0)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        return max(0.0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0)
    except Exception: return 0.0


# ---------------------------------------------------------------- 持久化
def state_path(home: Path) -> Path:
    return Path(home) / "companion" / "watching.json"


def save(w: Watcher, home: Path) -> None:
    p = state_path(home); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(w.to_dict(), ensure_ascii=False), "utf-8")
    os.replace(tmp, p)


def load(home: Path, cfg: dict | None = None) -> Watcher:
    try: return Watcher.from_dict(json.loads(state_path(home).read_text("utf-8")))
    except Exception: return Watcher(cfg)
