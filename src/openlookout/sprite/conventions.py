"""通用的“长期约定”学习器：从重复出现的纠正/提醒里推断持久约定，并带证据和置信度。
证据来源（统一成事件）：
  kind=instruction|correction  用户对代理/工具说的话、重复的修改说明（text, project, session, ts）
  kind=agent_rule              项目规则文件里已有的条目（跨项目重复 -> 全局约定候选）
  kind=<任意>, theme+theme_text  各种“检测器”提供的证据（如重复造轮子、重复犯同类错），按 theme 聚类
不含任何领域词表：是否是约定，取决于 ① 像不像“指令/偏好”的话语形式 ② 是否重复 ③ 是否跨时间/会话 ④ 是否不是只针对某个具体文件/任务 ⑤ 有没有互相矛盾的说法。
置信度 = 1 - exp(-Σ权重)：同一会话里连说几遍只算一次；任务专用（含路径/编号）的权重很低；检测器核实过的证据权重较高。"""
from __future__ import annotations
import hashlib, math, re
from dataclasses import dataclass, field
from datetime import datetime

MARK = re.compile(r"(不要|别|不许|禁止|不准|必须|务必|一定要|总是|永远|每次|记得|优先|尽量|应该|先.{1,12}再|之前先|之前要|完成后|写完|提交前|"
                  r"\bdon'?t\b|\bdo not\b|\bnever\b|\balways\b|\bmust\b|\bmake sure\b|\bprefer\b|\bshould\b|\bremember to\b|\bbefore you\b|\bbefore\b.*\bfirst\b)", re.I)
SPECIFIC = re.compile(r"([A-Za-z]:\\|/[\w.\-]+/[\w.\-]+|\b[\w\-]+\.(py|js|ts|md|json|yaml|toml|java|go|rs|c|cpp|html|css)\b|#\d+|\bL\d+\b|第\s*\d+\s*行|0x[0-9a-f]+|[0-9a-f]{7,40})", re.I)
NEG = re.compile(r"(不要|别|不许|禁止|不准|不能|\bdon'?t\b|\bdo not\b|\bnever\b|\bnot\b)", re.I)
FILLER = re.compile(r"^(请|麻烦|你要|你得|你应该|记住|注意|please|remember)[:：，, ]*", re.I)


def norm(t: str) -> str: return re.sub(r"[\s，。！？、；：,.!?;:\"'“”‘’（）()\[\]【】\-—_/\\*#>`]+", "", t.lower())
def grams(t: str) -> set:
    n = norm(t); g = {n[i:i + 2] for i in range(len(n) - 1)} | set(re.findall(r"[a-z]{3,}", t.lower()))
    return g
def sim(a: str, b: str) -> float:
    A, B = grams(a), grams(b)
    return 2 * len(A & B) / (len(A) + len(B)) if A and B else 0.0
def polarity(t: str) -> int: return -1 if NEG.search(t) else 1
def core(t: str) -> str: return NEG.sub("", t)
def is_instruction(t: str) -> bool:
    t = t.strip()
    return bool(MARK.search(t)) and not re.search(r"[?？]\s*$|吗[？?]?$|^(能不能|可不可以|是不是|为什么|怎么)", t) and len(t) >= 6


@dataclass
class Convention:
    id: str
    text: str
    scope: str                    # project | global
    project: str | None
    confidence: float
    evidence: list = field(default_factory=list)
    n_events: int = 0
    days: int = 0
    theme: str | None = None
    helper: dict | None = None
    missing_in: list = field(default_factory=list)       # 全局约定：哪些项目还没有


def cid(text: str) -> str: return hashlib.sha1(norm(text).encode()).hexdigest()[:8]


def rule_lines(text: str) -> list:
    out = []
    for l in text.splitlines():
        s = re.sub(r"^\s*([-*+]|\d+[.)])\s*", "", l).strip()
        if s and not s.startswith(("#", "<!--")) and is_instruction(s): out.append(s)
    return out


class ConventionLearner:
    def __init__(self, sim_thresh=0.5, min_conf=0.6, semantic=None):
        self.th, self.min_conf, self.semantic = sim_thresh, min_conf, semantic        # semantic(a,b)->bool：可选 tier1/2 语义合并，仅用于边界相似度
        self.log = []

    def _same(self, a, b):
        if polarity(a) != polarity(b): return False              # 极性相反的说法不合并（留给矛盾检测）
        s = sim(a, b)
        if s >= self.th: return True
        return bool(self.semantic and 0.05 <= s < self.th and self.semantic(a, b))

    def _cluster(self, items):
        cl = []
        for e in items:
            for c in cl:
                if self._same(c[0]["text"], e["text"]): c.append(e); break
            else: cl.append([e])
        return cl

    @staticmethod
    def _weight(e):
        if e.get("kind") == "agent_rule": return 0.5
        if e.get("source") == "detector": return 1.0 * e.get("strength", 1.0)
        w = 0.45
        if SPECIFIC.search(e["text"]): w *= 0.25                           # 任务专用：提到具体文件/行号/编号
        return w

    def _score(self, evs):
        # 同一(会话/天)内的重复只算一次（取最大）+ 很小的加成
        groups = {}
        for e in evs: groups.setdefault((e.get("project"), e.get("session") or str(e.get("ts", ""))[:10], e.get("source") == "detector"), []).append(self._weight(e))
        total = sum(max(ws) + 0.05 * (len(ws) - 1) for ws in groups.values())
        days = {str(e.get("ts", ""))[:10] for e in evs if e.get("ts")}
        conf = 1 - math.exp(-total)
        if len(days) < 2 and not any(e.get("source") == "detector" for e in evs) and not any(e.get("kind") == "agent_rule" for e in evs): conf *= 0.6
        return conf, len(days)

    def infer(self, events, rule_files: dict | None = None, rejected: set | None = None, active_projects=()) -> list:
        rule_files = rule_files or {}; rejected = rejected or set(); out = []; self.log = []
        user = [e for e in events if e.get("kind") in ("instruction", "correction") and is_instruction(e.get("text", ""))]
        ruled = [dict(kind="agent_rule", project=p, text=l, ts=None) for p, t in rule_files.items() for l in rule_lines(t)]
        det = [e for e in events if e.get("theme")]
        # —— 检测器证据：按 (theme, project) 聚类
        by = {}
        for e in det: by.setdefault((e["theme"], e.get("project")), []).append(e)
        for (theme, proj), evs in by.items():
            conf, days = self._score(evs); text = evs[-1]["theme_text"]
            out.append(Convention(cid(text), text, "project", proj, round(conf, 2), [e["text"] for e in evs[-4:]], len(evs), days, theme, evs[-1].get("helper")))
        # —— 语言证据 + 规则文件证据：跨项目聚类
        for cl in self._cluster(user + ruled):
            texts = [e["text"] for e in cl]; canon = FILLER.sub("", sorted(texts, key=lambda t: abs(len(t) - sum(map(len, texts)) / len(texts)))[0]).strip()
            projs = {e.get("project") for e in cl if e.get("project")}
            if len(projs) >= 3:                                          # 跨 3 个以上项目：全局约定，缺它的项目是落地对象
                conf, days = self._score(cl); missing = [p for p in active_projects if p not in projs]
                out.append(Convention(cid(canon), canon, "global", None, round(conf, 2), texts[-4:], len(cl), days, None, None, missing)); continue
            for p in (projs or {None}):
                sub = [e for e in cl if e.get("project") == p]
                conf, days = self._score(sub)
                if sub and all(e.get("kind") == "agent_rule" for e in sub): continue          # 只是规则文件里已经有的，不需要再落
                out.append(Convention(cid(canon), canon, "project", p, round(conf, 2), [e["text"] for e in sub[-4:]], len(sub), days))
        # —— 矛盾：核心相同、极性相反 -> 都不落
        bad = set()
        for i, a in enumerate(out):
            for b in out[i + 1:]:
                if a.theme is None and b.theme is None and a.project == b.project and sim(core(a.text), core(b.text)) >= 0.6 and polarity(a.text) != polarity(b.text): bad |= {a.id, b.id}
        res = []
        for c in out:
            if c.id in bad: self.log.append((c.text, "互相矛盾，不落")); continue
            if (c.id, c.project) in rejected or c.id in rejected: self.log.append((c.text, "你撤销过，不再提")); continue
            if c.confidence < self.min_conf: self.log.append((c.text, f"置信度 {c.confidence} 不够")); continue
            if c.scope == "project" and c.project and self._present(rule_files.get(c.project, ""), c): self.log.append((c.text, "规则文件里已有")); continue
            res.append(c)
        return res

    def _present(self, text, conv):
        if f"openlookout:conv:{conv.id}" in text: return True
        return any(sim(l, conv.text) >= 0.5 for l in rule_lines(text)) or (conv.theme and sim(text, conv.text) >= 0.5)
