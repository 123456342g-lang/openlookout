"""新颖问题理解（tier2 云端大模型）：**默认**负责「这是什么问题」。

通用环：观察异常/代价/僵局 → 取证凑证据包 → **云端 novel 理解（默认，给未解除的 open 问题）**
  → 白名单可逆执行 → recheck 直到解除。

本地不做「主理解」：本地 = 传感器 + 动作白名单 + 预算；理解 = novel/cloud。
本地 judge 只做安全闸（self/protected）与证据整理；不靠本地启发式套路给问题定性。
网络/僵局/压力等是传感器与执行器插件，不是「先查是不是网络」的主脑路径。

不做：常驻截图、自由 shell、把「不认识」升成「自动做高风险」。
模型只能建议白名单动作 kind；真正执行仍靠已注册 responder / archive_note。
默认云端关闭（无 client）；测试用 FakeNovelClient；真机设 OPENLOOKOUT_NOVEL=1 + 密钥。
"""
from __future__ import annotations
import json, os, re, time, urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from .investigate import Candidate, Understanding
from .tiers import Meter, Budget, PRICE
from .framework import Action

# 白名单：LLM 不得发明 shell / 任意路径删除
ALLOWED_ACTION_KINDS = frozenset({
    "skip",
    "archive_note",
    "stalemate_note",
    "net_flushdns",
    "net_restart_client",
    "net_rasdial",
    "open_help",
})
ALLOWED_STATES = frozenset({
    "in_use", "under_development", "abandoned", "stale_duplicate",
    "vendor", "protected", "self", "unknown",
})
ALLOWED_RISKS = frozenset({"safe", "medium", "high"})

SYSTEM_NOVEL = (
    "你是桌面小精灵的理解器。根据脱敏证据包判断用户电脑上遇到了什么任意问题（不预设是网络或其他某一类）。"
    "只输出一个 JSON 对象，不要 markdown。字段："
    '{"what":"<=80字","why":"<=120字","state":"unknown|in_use|abandoned|stale_duplicate|under_development|protected|vendor|self",'
    '"confidence":0.0到1.0,"act":true或false,'
    '"candidate_actions":[{"kind":"白名单之一","args":{},"reason":"<=60字","risk":"safe|medium","reversible":"full"}]}。'
    "白名单 kind 仅允许：skip, archive_note, stalemate_note, net_flushdns, net_restart_client, net_rasdial, open_help。"
    "不可还原或拿不准就 act=false 且 candidate_actions 用 skip。"
    "不要编造证据里没有的主机/路径/进程；不要建议安装软件或删文件。"
)


def needs_novel(u: Understanding, min_conf: float = 0.75, *, prefer_novel: bool = True) -> bool:
    """是否调用云端理解。

    默认 prefer_novel=True：未解除的 open 问题由云端定性（本地启发式不是主理解）。
    仅跳过硬安全闸 self/protected（绝不动自己/受保护对象，无需问云端改口）。
    prefer_novel=False 时退回旧「本地自信则跳过」路径（省预算/兼容）。
    """
    if u.state in ("self", "protected"):
        return False
    if prefer_novel:
        return True
    # legacy escalate-only
    if u.act and u.confidence >= 0.60:
        return False
    if u.state == "unknown":
        return True
    if (not u.act) and u.confidence < min_conf:
        return True
    if u.act and u.confidence < 0.55:
        return True
    return False


def build_evidence_pack(
    cand: Candidate,
    facts: dict,
    evidence: list | None = None,
    *,
    vision_caption: str = "",
    prior: Understanding | None = None,
    recent_understandings: list | None = None,
) -> dict:
    """结构化证据包：只含可 JSON 化、尽量脱敏的字段。"""
    safe_facts = {}
    for k, v in (facts or {}).items():
        if k.startswith("_"):
            continue
        if isinstance(v, (str, int, float, bool, type(None))):
            safe_facts[k] = v if not isinstance(v, str) else v[:500]
        elif isinstance(v, list):
            safe_facts[k] = v[:20]
        elif isinstance(v, dict):
            try:
                safe_facts[k] = json.loads(json.dumps(v, default=str)[:2000])
            except Exception:
                safe_facts[k] = str(v)[:300]
    pack = dict(
        kind=cand.kind,
        key=cand.key,
        title=(cand.title or "")[:120],
        signals={k: v for k, v in (cand.signals or {}).items()
                 if isinstance(v, (str, int, float, bool, list, type(None)))},
        facts=safe_facts,
        evidence=[str(x)[:200] for x in (evidence or [])][:30],
        vision_caption=(vision_caption or "")[:300],
        local_prior=None,
        recent=[],
    )
    if prior is not None:
        pack["local_prior"] = dict(
            state=prior.state, confidence=prior.confidence, act=prior.act,
            what=(prior.what or "")[:120], why=(prior.why or "")[:160],
        )
    for u in (recent_understandings or [])[-5:]:
        if isinstance(u, Understanding):
            pack["recent"].append(dict(kind=u.kind, state=u.state, what=(u.what or "")[:80]))
        elif isinstance(u, dict):
            pack["recent"].append({k: u.get(k) for k in ("kind", "state", "what")})
    return pack


def validate_novel_payload(raw: dict | str) -> dict:
    """Schema 校验；非法字段丢弃/钳制。返回规范化 dict。"""
    if isinstance(raw, str):
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError("no json object")
        raw = json.loads(m.group(0))
    if not isinstance(raw, dict):
        raise ValueError("payload not object")
    state = str(raw.get("state") or "unknown")
    if state not in ALLOWED_STATES:
        state = "unknown"
    conf = float(raw.get("confidence") or 0.0)
    conf = max(0.0, min(1.0, conf))
    act = bool(raw.get("act"))
    actions = []
    for a in (raw.get("candidate_actions") or [])[:5]:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind") or "skip")
        if kind not in ALLOWED_ACTION_KINDS:
            continue
        risk = str(a.get("risk") or "safe")
        if risk not in ALLOWED_RISKS:
            risk = "high"
        rev = str(a.get("reversible") or "full")
        if rev not in ("full", "regen", "partial", "none"):
            rev = "none"
        # 高风险或不可逆 → 强制 skip，永不自动做
        if risk == "high" or rev in ("partial", "none"):
            kind, risk, rev, act = "skip", "safe", "full", False
        args = a.get("args") if isinstance(a.get("args"), dict) else {}
        # args 只保留简单标量
        clean_args = {str(k)[:40]: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v)[:80])
                      for k, v in list(args.items())[:8]}
        actions.append(dict(
            kind=kind, args=clean_args,
            reason=str(a.get("reason") or "")[:80],
            risk=risk, reversible=rev,
        ))
    if not actions:
        actions = [dict(kind="skip", args={}, reason="无安全候选", risk="safe", reversible="full")]
    # 若唯一候选是 skip，不能 act
    if all(a["kind"] == "skip" for a in actions):
        act = False
    # 模型永远不能把 unknown 低置信硬抬成自动高风险；act 时置信至少 0.6
    if act and conf < 0.6:
        act = False
    return dict(
        what=str(raw.get("what") or "")[:120],
        why=str(raw.get("why") or "")[:200],
        state=state,
        confidence=conf,
        act=act,
        candidate_actions=actions,
    )


def understanding_from_payload(cand: Candidate, payload: dict, facts: dict, evidence: list, ts: float) -> Understanding:
    u = Understanding(
        cand.key, cand.kind, cand.title,
        what=payload["what"] or facts.get("what", ""),
        owner=facts.get("owner", "novel"),
        state=payload["state"],
        confidence=payload["confidence"],
        evidence=list(evidence or []),
        facts=dict(facts or {}),
        act=payload["act"],
        why=payload["why"] or "云端新颖理解",
        ts=ts,
    )
    u.facts["novel"] = True
    u.facts["novel_actions"] = payload["candidate_actions"]
    u.evidence = (u.evidence or []) + [f"[novel] {payload['why']}"[:200]]
    return u


class FakeNovelClient:
    """测试用：返回预设 JSON 文本；(text, tin, tout)。"""
    def __init__(self, payload: dict | None = None, fn: Callable | None = None, fail: bool = False):
        self.payload = payload or dict(
            what="测试新颖问题", why="本地证据不足，建议只记笔记",
            state="unknown", confidence=0.7, act=True,
            candidate_actions=[dict(kind="archive_note", args={}, reason="记下待跟进", risk="safe", reversible="full")],
        )
        self.fn = fn
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> tuple[str, int, int]:
        self.calls.append((system, user))
        if self.fail:
            raise RuntimeError("fake cloud down")
        if self.fn:
            out = self.fn(system, user)
            if isinstance(out, tuple):
                return out
            text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
            return text, 100, 50
        return json.dumps(self.payload, ensure_ascii=False), 120, 80


def env_novel_enabled() -> bool:
    return os.environ.get("OPENLOOKOUT_NOVEL", "").strip().lower() in ("1", "true", "yes", "on")


def make_env_cloud_client():
    """真实云端：优先 OPENAI_API_KEY + OPENAI_BASE_URL；否则 ~/.config/ai-butler/mimo.env。
    未配置时返回 None（不抛）。"""
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENLOOKOUT_API_KEY")
    base = (os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENLOOKOUT_BASE_URL")
            or "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENLOOKOUT_NOVEL_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    if not key:
        env_path = Path(os.path.expanduser("~/.config/ai-butler/mimo.env"))
        if env_path.is_file():
            env = {}
            for l in env_path.read_text("utf-8").splitlines():
                if "=" in l and not l.startswith("#"):
                    k, v = l.split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
            key = env.get("MIMO_API_KEY")
            base = (env.get("MIMO_BASE_URL") or base).rstrip("/")
            model = env.get("MIMO_MODEL") or "mimo-v2.6-flash"
    if not key:
        return None

    def call(system: str, user: str) -> tuple[str, int, int]:
        body = json.dumps({
            "model": model, "temperature": 0.2, "max_tokens": 500,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }).encode()
        req = urllib.request.Request(
            base + "/chat/completions", body,
            {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        j = json.loads(urllib.request.urlopen(req, timeout=60).read())
        u = j.get("usage", {})
        text = (j["choices"][0]["message"].get("content") or "")
        return text, int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)

    return call


@dataclass
class NovelUnderstander:
    """tier2 新颖理解器。enabled=False 或无 client 时 understand() 返回 None（跳过）。"""
    home: Path
    clock: Callable = time.time
    client: Callable | None = None
    daily_tokens: int = 8000
    daily_usd: float = 0.05
    enabled: bool = False
    est_tokens: int = 700
    min_local_skip_conf: float = 0.75   # prefer_novel=False 时：本地已够置信则不调用
    prefer_novel: bool = True           # True：open 问题默认走云端理解
    log: Callable = lambda *a: None
    _meter: Meter = field(init=False, repr=False)
    _budget: Budget = field(init=False, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.home = Path(self.home)
        self.home.mkdir(parents=True, exist_ok=True)
        self._meter = Meter(self.home / "tokens.jsonl", self.clock)
        self._budget = Budget(self._meter, self.daily_tokens, self.daily_usd)

    @classmethod
    def from_env(cls, home: Path, clock=time.time, log=lambda *a: None, **kw):
        """未设 OPENLOOKOUT_NOVEL 或无密钥时返回 None（不挂上理解器）。"""
        if not env_novel_enabled():
            return None
        client = make_env_cloud_client()
        if client is None:
            log("OPENLOOKOUT_NOVEL=1 但未找到 API 密钥，跳过云端新颖理解")
            return None
        return cls(home=home, clock=clock, client=client, enabled=True, log=log, **kw)

    def meter_today(self) -> dict:
        return self._meter.today()

    def understand(
        self,
        cand: Candidate,
        facts: dict,
        evidence: list | None = None,
        *,
        prior: Understanding | None = None,
        vision_caption: str = "",
        recent: list | None = None,
        force: bool = False,
    ) -> Understanding | None:
        prefer = bool(getattr(self, "prefer_novel", True))
        if prior is not None and not force and not needs_novel(prior, self.min_local_skip_conf, prefer_novel=prefer):
            self._meter.record(0, "novel_skip_local_confident", decision=cand.key)
            return None
        if not self.enabled or self.client is None:
            self._meter.record(0, "novel_skip_disabled", decision=cand.key)
            return None
        # 短缓存：同一 key 10 分钟内不重复烧 token
        now = float(self.clock())
        hit = self._cache.get(cand.key)
        if hit and not force and now - hit[0] < 600:
            self._meter.record(0, "novel_cache", cached=True, decision=cand.key)
            return hit[1]
        if not self._budget.allow(self.est_tokens):
            self._meter.record(0, "novel_degraded_budget", decision=cand.key)
            self.log("新颖理解：今日云端预算用完，跳过")
            return None
        pack = build_evidence_pack(
            cand, facts, evidence,
            vision_caption=vision_caption, prior=prior, recent_understandings=recent,
        )
        user = json.dumps(pack, ensure_ascii=False)
        try:
            text, tin, tout = self.client(SYSTEM_NOVEL, user)
        except Exception as e:
            self._meter.record(0, "novel_error", decision=cand.key)
            self.log(f"新颖理解调用失败：{type(e).__name__}")
            return None
        self._meter.record(2, "novel_understand", tin, tout, decision=cand.key)
        try:
            payload = validate_novel_payload(text)
        except Exception as e:
            self._meter.record(0, "novel_parse_fail", decision=cand.key)
            self.log(f"新颖理解解析失败：{type(e).__name__}")
            return None
        u = understanding_from_payload(cand, payload, facts, evidence or [], now)
        self._cache[cand.key] = (now, u)
        self.log("新颖理解：" + u.line())
        return u


def archive_note_action(cand: Candidate, u: Understanding, home: Path) -> Action:
    """白名单 archive_note / stalemate_note：只写 home 下笔记，可撤销。"""
    notes = Path(home) / "novel_notes"
    notes.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]+", "_", cand.key)[:80] + ".json"
    note = notes / safe
    payload = dict(
        key=cand.key, kind=cand.kind, title=cand.title, what=u.what, why=u.why,
        state=u.state, confidence=u.confidence,
        novel_actions=u.facts.get("novel_actions"), ts=u.ts or time.time(),
    )

    def dry(): return True
    def run():
        note.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return dict(note=str(note))
    def verify(r): return Path((r or {}).get("note") or note).is_file()
    def undo(r):
        try:
            Path((r or {}).get("note") or note).unlink(missing_ok=True)
        except OSError:
            pass

    return Action(
        "novel_archive_note",
        f"记下新颖理解：{(cand.title or '')[:40]}",
        "safe", "full", relief=0.4, reason=u.why, confident=True, value_s=90.0,
        dry_run=dry, run=run, verify=verify, undo=undo,
        done_text=lambda xs: f"已记下新颖理解：{(u.what or cand.title or '')[:40]}",
        done_short=lambda xs: "已记下新颖理解",
    )


def propose_novel_actions(cand: Candidate, u: Understanding, world=None) -> list:
    """把 novel_actions 映射为可逆 Action；未知 kind 忽略。网络类动作若本 kind 已有 responder，通常由原 propose 处理。"""
    home = Path(getattr(world, "home", None) or (u.facts or {}).get("home") or cand.ctx.get("home") or ".")
    acts = []
    for a in (u.facts or {}).get("novel_actions") or []:
        kind = a.get("kind")
        if kind in ("archive_note", "stalemate_note", "open_help"):
            acts.append(archive_note_action(cand, u, home))
            break
        if kind == "skip":
            continue
        # net_* ：仅当候选本身是 network_break 时留给 network propose；这里不造 rasdial
        if kind.startswith("net_"):
            continue
    return acts
