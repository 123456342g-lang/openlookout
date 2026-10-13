# -*- coding: utf-8 -*-
"""Surgical patch for network.py: HTTP reachability, browse-from-events, running-proxy restart, system proxy."""
from __future__ import annotations
import re
from pathlib import Path

p = Path(r"E:\OpenLookout\src\openlookout\sprite\scenarios\network.py")
t = p.read_text(encoding="utf-8")

# --- 1) Update module docstring ---
t = re.sub(
    r'^""".*?"""',
    '''"""网络不可达 / 浏览失败：只通过 investigate.InvestigatorRegistry 注册，核心零改动。
发现器 network_break：通用信号——监视主机 HTTP(S) 真实失败（拒绝把 Clash fake-ip 的 TCP 假通算可达）、
DNS 失败、无默认路由、本机代理端口死掉、已知 VPN/代理客户端曾在跑现已退出、录制器里最近浏览失败目标。
取证：DNS、HTTP(S) 短请求（系统默认栈、绕过环境代理）、系统代理、常见 VPN/代理客户端、Windows VPN、
对浏览目标做直连 TCP/HTTP 区分「代理/TUN 劫持」vs「目标服务空响应」。
理解写入 understandings.jsonl。可逆动作（轻→重）：flushdns → 启用系统代理（若端口在听）→
重启用户已有本地代理客户端（含在跑但已坏）→ rasdial 已有系统 VPN；浏览局域网被代理吃掉时优先可逆动代理。
绝不删应用、不安新 VPN、不永久改防火墙、不问用户。recheck=HTTP 重新成功才解除。"""''',
    t, count=1, flags=re.S)

# --- 2) Add imports urllib ---
if "urllib.request" not in t:
    t = t.replace(
        "import json, os, re, socket, subprocess, time",
        "import ipaddress, json, os, re, socket, subprocess, time, urllib.error, urllib.request",
    )

# --- 3) After DEFAULT_HOSTS, insert helpers + extend ProbeResult ---
HELPERS = r'''
# Clash fake-ip 常用网段；TCP 通了也不算可达，必须 HTTP/TLS 成功
FAKE_IP_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),)
PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
)
BROWSER_APP_RE = re.compile(r"chrome|msedge|edge|firefox|brave|opera|vivaldi|chromium", re.I)
# 从窗口标题抽主机：IP 或域名（排除纯软件名）
HOST_IN_TITLE_RE = re.compile(
    r"(?i)(?:https?://)?("
    r"(?:\d{1,3}\.){3}\d{1,3}"
    r"|[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?)+"
    r")(?::\d{2,5})?(?:[/?\s\-]|$)"
)
ERR_IN_TITLE_RE = re.compile(
    r"ERR_[A-Z0-9_]+|无法访问|无法正常运作|未发送任何|Empty Response|This site can.?t be reached|"
    r"连接已重置|拒绝连接|Timed out|ERR_EMPTY|ERR_CONNECTION|ERR_TUNNEL|ERR_PROXY|ERR_NAME",
    re.I,
)
HTTP_OK_STATUSES = set(range(200, 400)) | {204}


def _ip_in(networks, addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    return any(ip in n for n in networks)


def is_fake_ip(addr: str) -> bool:
    return _ip_in(FAKE_IP_NETWORKS, addr or "")


def is_private_ip(addr: str) -> bool:
    return _ip_in(PRIVATE_NETWORKS, addr or "")


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address((host or "").split("%")[0]); return True
    except ValueError:
        return False


def events_candidates(home: Path) -> list[Path]:
    """通用：sprite home、仓库 data/、常见 capture 路径；不绑死某一台机器。"""
    home = Path(home)
    cands = [
        home / "events.jsonl",
        home.parent / "data" / "events.jsonl",
        home.parent / "data" / "pet" / "capture" / "events.jsonl",
        home / "capture" / "events.jsonl",
    ]
    # 若 home 在 .../sprite_home，再试同级 OpenLookout/data
    try:
        root = home.resolve().parent
        cands.append(root / "data" / "events.jsonl")
    except Exception:
        pass
    out, seen = [], set()
    for c in cands:
        try:
            r = c.resolve()
        except Exception:
            r = c
        if r in seen: continue
        seen.add(r)
        if c.is_file(): out.append(c)
    return out


def parse_browse_signals(paths: list[Path], now_ts: float, window_s: float = 900.0) -> list[dict]:
    """从录制器 focus 标题里抽最近浏览目标（主机/IP）与错误暗示。不注入任何固定 URL。"""
    import datetime as _dt
    agg: dict[str, dict] = {}
    for path in paths:
        try:
            # 只读尾部，避免大文件
            data = path.read_bytes()
            if len(data) > 2_000_000:
                data = data[-2_000_000:]
            text = data.decode("utf-8", "replace")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line: continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") != "focus": continue
            app = str(e.get("app") or "")
            if not BROWSER_APP_RE.search(app): continue
            title = str(e.get("title") or "")
            ts_raw = e.get("ts") or ""
            # 解析时间
            tsec = None
            if isinstance(ts_raw, (int, float)):
                tsec = float(ts_raw)
            else:
                try:
                    tsec = _dt.datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).timestamp()
                except Exception:
                    tsec = None
            if tsec is not None and now_ts - tsec > window_s:
                continue
            err = bool(ERR_IN_TITLE_RE.search(title))
            m = HOST_IN_TITLE_RE.search(title)
            if not m:
                continue
            host = m.group(1).rstrip(".-").lower()
            # 过滤明显不是站点的标题残片
            if host in ("google.com", "microsoft.com") and "chrome" in title.lower() and not err:
                # 「xxx - Google Chrome」里 Chrome 品牌不是目标；IP/内网/带错误才收
                if not is_ip_literal(host) and not err:
                    continue
            # 标题形如 "172.x - Google Chrome" / "host - Google Chrome"：host 是目标
            if re.search(r"(?i)\b(google chrome|microsoft.?edge|firefox|brave)\b", host):
                continue
            slot = agg.setdefault(host, dict(host=host, count=0, err=False, last_ts=tsec or 0, titles=[]))
            slot["count"] += 1
            slot["err"] = slot["err"] or err
            slot["last_ts"] = max(slot["last_ts"], tsec or 0)
            if title and title not in slot["titles"] and len(slot["titles"]) < 3:
                slot["titles"].append(title[:120])
    # 至少出现 2 次，或带错误关键字，才当作信号（降噪）
    out = [v for v in agg.values() if v["count"] >= 2 or v["err"]]
    out.sort(key=lambda x: (-x["count"], -x["last_ts"]))
    return out[:12]

'''

# Insert helpers after DEFAULT_HOSTS block
if "def is_fake_ip" not in t:
    t = t.replace(
        '    dict(host="1.1.1.1", tag="ip", skip_dns=True),\n)\n\n\n@dataclass\nclass ProbeResult:',
        '    dict(host="1.1.1.1", tag="ip", skip_dns=True),\n)\n'
        + HELPERS
        + "\n@dataclass\nclass ProbeResult:",
    )

# Extend ProbeResult fields
old_pr = '''@dataclass
class ProbeResult:
    host: str
    tag: str
    dns_ok: bool = False
    dns_addrs: list = field(default_factory=list)
    dns_err: str = ""
    tcp_ok: bool = False
    tcp_ms: float = -1.0
    tcp_err: str = ""
'''
new_pr = '''@dataclass
class ProbeResult:
    host: str
    tag: str
    dns_ok: bool = False
    dns_addrs: list = field(default_factory=list)
    dns_err: str = ""
    tcp_ok: bool = False
    tcp_ms: float = -1.0
    tcp_err: str = ""
    http_ok: bool = False
    http_status: int = 0
    http_ms: float = -1.0
    http_err: str = ""
    fake_ip: bool = False
    # reach_ok：真实可达。fake-ip 上仅 TCP 通不算。
    reach_ok: bool = False
'''
if "reach_ok: bool" not in t:
    t = t.replace(old_pr, new_pr)

p.write_text(t, encoding="utf-8")
print("phase1 ok, lines", len(t.splitlines()))