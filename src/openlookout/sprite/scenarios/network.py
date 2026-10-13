"""网络传感器 / 执行器插件（不是主脑，不「先查是不是网络问题」）。

只通过 investigate.InvestigatorRegistry 注册。产品通用环是：任意异常→取证→云端理解→白名单可逆执行。
本文件只提供：
  传感器 discover：HTTP 真失败 / DNS / 无路由 / 代理端口死 / 客户端曾在跑现退出 / 录制器浏览失败
  取证 gather：DNS、HTTP、系统代理、VPN/代理客户端、Windows VPN、直连 vs 代理劫持
  白名单执行 propose：flushdns → 重启已有本地代理 → rasdial 已有系统 VPN
  recheck：可达则解除

本地 judge 只整理白名单线索，不把「这是什么问题」写成网络故事线主理解（定性默认交给 novel）。
绝不删应用、不安新 VPN、不永久改防火墙、不问用户。不硬编码用户主机。"""
from __future__ import annotations
import ipaddress, json, os, re, socket, subprocess, time, urllib.error, urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from ..framework import Action
from ..investigate import (Candidate, Understanding, InvestigatorRegistry, Investigator,
                           register_generic, investigator_scenario, NO_WINDOW)

# 客户端族：用进程名/路径关键字识别，不绑死单一产品
VPN_FAMILIES = (
    dict(id="clash_verge", labels=("Clash Verge",), proc=re.compile(r"clash-verge|verge-mihomo|clash.verge", re.I),
         path_keys=("clashverge", "clash-verge", "clash.verge"), exe_names=("clash-verge.exe",)),
    dict(id="clash", labels=("Clash",), proc=re.compile(r"clash for windows|clash-win|(?:^|[\/])clash\.exe\b", re.I),
         path_keys=("clash for windows", "clash-for-windows"), exe_names=("Clash for Windows.exe", "clash.exe")),
    dict(id="v2rayn", labels=("v2rayN",), proc=re.compile(r"v2rayn|v2ray\\\\|xray\\\\|nevora|nekoray", re.I),
         path_keys=("v2rayn", "nekoray"), exe_names=("v2rayN.exe", "nekoray.exe")),
    dict(id="openvpn", labels=("OpenVPN",), proc=re.compile(r"openvpn", re.I),
         path_keys=("openvpn",), exe_names=("openvpn.exe", "openvpn-gui.exe")),
    dict(id="tailscale", labels=("Tailscale",), proc=re.compile(r"tailscale", re.I),
         path_keys=("tailscale",), exe_names=("tailscale-ipn.exe", "tailscaled.exe")),
    dict(id="wireguard", labels=("WireGuard",), proc=re.compile(r"wireguard|wg\\\\.exe", re.I),
         path_keys=("wireguard",), exe_names=("wireguard.exe",)),
    dict(id="singbox", labels=("sing-box",), proc=re.compile(r"sing-box|singbox|hysteria", re.I),
         path_keys=("sing-box", "hysteria"), exe_names=("sing-box.exe",)),
)

DEFAULT_HOSTS = (
    dict(host="www.baidu.com", tag="domestic"),
    dict(host="www.qq.com", tag="domestic"),
    dict(host="www.google.com", tag="foreign"),
    dict(host="github.com", tag="foreign"),
    dict(host="1.1.1.1", tag="ip", skip_dns=True),
)

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
    """从录制器抽最近浏览失败信号。优先 browser_error / 带 url 的事件；focus 标题 ERR_* 仅为弱信号。
不注入任何固定 URL。真正 ERR_* 路径依赖 recorder 发出 browser_error（见 observe/ + recorder_ext）。"""
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
            typ = e.get("type")
            # --- real browse-failure path (extension → recorder) ---
            if typ == "browser_error":
                url = str(e.get("url") or "")
                host = ""
                murl = re.match(r"(?i)^(?:https?://)?([^/\s?#:]+)", url.strip()) if url else None
                if murl:
                    host = murl.group(1).lower().rstrip(".")
                code = str(e.get("error") or e.get("code") or "ERR_FAILED")
                ts_raw = e.get("ts") or ""
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
                key = host or f"err:{code}"
                slot = agg.setdefault(key, dict(host=host, count=0, err=True, last_ts=tsec or 0, titles=[], codes=[], source="browser_error"))
                slot["count"] += 1
                slot["err"] = True
                slot["last_ts"] = max(slot["last_ts"], tsec or 0)
                slot["source"] = "browser_error"
                if code and code not in slot.get("codes", []):
                    slot.setdefault("codes", []).append(code)
                if url and url not in slot.get("titles", []) and len(slot.get("titles", [])) < 3:
                    slot.setdefault("titles", []).append(url[:120])
                continue
            if typ in ("nav", "url"):
                # Successful navigation alone is not a failure signal; skip.
                continue
            if typ != "focus":
                continue
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


@dataclass
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


@dataclass
class VpnClient:
    family: str
    label: str
    running: bool
    pids: list = field(default_factory=list)
    exes: list = field(default_factory=list)
    install_path: str = ""
    start_exe: str = ""           # 可用来重新拉起的主程序
    listen_ports: list = field(default_factory=list)


@dataclass
class WinVpn:
    name: str
    status: str                   # Connected / Disconnected / ...
    server: str = ""


class RealNetView:
    """真实网络探针；测试换成假的。"""
    def __init__(self, timeout=2.5):
        self.timeout = timeout
        try:
            import psutil; self.ps = psutil
        except Exception:
            self.ps = None

    def now(self): return time.time()

    def resolve(self, host: str) -> tuple[bool, list, str]:
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            addrs = sorted({i[4][0] for i in infos})
            return True, addrs, ""
        except Exception as e:
            return False, [], f"{type(e).__name__}:{e}"

    def tcp443(self, host: str) -> tuple[bool, float, str]:
        t0 = time.time()
        try:
            s = socket.create_connection((host, 443), timeout=self.timeout)
            s.close()
            return True, (time.time() - t0) * 1000, ""
        except Exception as e:
            return False, (time.time() - t0) * 1000, f"{type(e).__name__}:{e}"

    def default_route(self) -> bool:
        try:
            r = subprocess.run(["route", "print", "-4"], capture_output=True, timeout=8, creationflags=NO_WINDOW)
            text = (r.stdout or b"").decode("utf-8", "replace") + (r.stdout or b"").decode("gbk", "replace")
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    return True
            return False
        except Exception:
            return True  # 不确定时不当成断路由，避免误报

    def system_proxy(self) -> dict:
        out = dict(env_http=os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "",
                   env_https=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "",
                   enable=False, server="", pac="", override="")
        if os.name != "nt": return out
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            try: out["enable"] = bool(winreg.QueryValueEx(k, "ProxyEnable")[0])
            except OSError: pass
            try: out["server"] = str(winreg.QueryValueEx(k, "ProxyServer")[0] or "")
            except OSError: pass
            try: out["pac"] = str(winreg.QueryValueEx(k, "AutoConfigURL")[0] or "")
            except OSError: pass
            try: out["override"] = str(winreg.QueryValueEx(k, "ProxyOverride")[0] or "")
            except OSError: pass
            winreg.CloseKey(k)
        except Exception: pass
        return out

    def set_system_proxy(self, *, enable=None, server=None, override=None) -> dict:
        """可逆改 HKCU 系统代理；返回改前快照。非 Windows 空操作。"""
        prior = self.system_proxy()
        if os.name != "nt":
            return dict(prior_enable=prior.get("enable"), prior_server=prior.get("server"), prior_override=prior.get("override"))
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        try:
            if enable is not None:
                winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enable else 0)
            if server is not None:
                winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, str(server))
            if override is not None:
                winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, str(override))
        finally:
            winreg.CloseKey(k)
        # 通知 WinInet 设置变更（尽力）
        try:
            import ctypes
            internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
            internet_set_option(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
            internet_set_option(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH
        except Exception:
            pass
        return dict(prior_enable=prior.get("enable"), prior_server=prior.get("server"), prior_override=prior.get("override"))

    def tcp_port(self, host: str, port: int) -> tuple[bool, float, str]:
        t0 = time.time()
        try:
            s = socket.create_connection((host, int(port)), timeout=self.timeout)
            s.close()
            return True, (time.time() - t0) * 1000, ""
        except Exception as e:
            return False, (time.time() - t0) * 1000, f"{type(e).__name__}:{e}"

    def http_get(self, url: str, timeout: float | None = None) -> tuple[bool, int, float, str]:
        """短 HTTP(S) GET，强制不走环境代理；2xx/3xx/204 算成功。"""
        to = self.timeout if timeout is None else timeout
        t0 = time.time()
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "OpenLookout-sprite/1", "Accept": "*/*"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=to) as resp:
                status = int(getattr(resp, "status", None) or resp.getcode() or 0)
                # 读一点 body 触发真正的空响应/半开连接
                try: resp.read(64)
                except Exception: pass
                ok = status in HTTP_OK_STATUSES
                return ok, status, (time.time() - t0) * 1000, "" if ok else f"status:{status}"
        except Exception as e:
            return False, 0, (time.time() - t0) * 1000, f"{type(e).__name__}:{e}"
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings")
            try: out["enable"] = bool(winreg.QueryValueEx(k, "ProxyEnable")[0])
            except OSError: pass
            try: out["server"] = str(winreg.QueryValueEx(k, "ProxyServer")[0] or "")
            except OSError: pass
            try: out["pac"] = str(winreg.QueryValueEx(k, "AutoConfigURL")[0] or "")
            except OSError: pass
            winreg.CloseKey(k)
        except Exception: pass
        return out

    def port_listening(self, port: int) -> bool:
        if not self.ps: return False
        try:
            for c in self.ps.net_connections(kind="inet"):
                if c.status == "LISTEN" and c.laddr and int(c.laddr.port) == int(port):
                    return True
        except Exception: pass
        return False

    def listen_ports_by_pid(self) -> dict:
        out = {}
        if not self.ps: return out
        try:
            for c in self.ps.net_connections(kind="inet"):
                if c.status == "LISTEN" and c.pid and c.laddr:
                    out.setdefault(c.pid, []).append(int(c.laddr.port))
        except Exception: pass
        return out

    def procs_blob(self) -> list:
        """[(pid, name, exe, cmdline_str)]"""
        if not self.ps: return []
        rows = []
        try:
            for p in self.ps.process_iter(["pid", "name", "exe", "cmdline"]):
                i = p.info
                try:
                    rows.append((i["pid"], i["name"] or "", i["exe"] or "", " ".join(i["cmdline"] or [])))
                except Exception: continue
        except Exception: pass
        return rows

    def win_vpns(self) -> list[WinVpn]:
        if os.name != "nt": return []
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-VpnConnection -ErrorAction SilentlyContinue | Select-Object Name,ConnectionStatus,ServerAddress | ConvertTo-Json -Compress"],
                capture_output=True, timeout=15, creationflags=NO_WINDOW)
            raw = (r.stdout or b"").decode("utf-8", "replace").strip()
            if not raw: return []
            data = json.loads(raw); data = data if isinstance(data, list) else [data]
            return [WinVpn(str(d.get("Name") or ""), str(d.get("ConnectionStatus") or ""), str(d.get("ServerAddress") or "")) for d in data if d.get("Name")]
        except Exception:
            return []

    def rasdial_status(self) -> list[str]:
        if os.name != "nt": return []
        try:
            r = subprocess.run(["rasdial"], capture_output=True, timeout=8, creationflags=NO_WINDOW)
            text = (r.stdout or b"").decode("gbk", "replace")
            # 已连接的连接名在输出里；无连接时中文提示
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines: return []
            joined = "\\n".join(lines)
            if "No connections" in joined or "没有连接" in joined or "没有已连接" in joined:
                return []
            # rasdial 无参时列出已连接名
            skip = {"Connected", "已连接", "Command completed successfully.", "命令已成功完成。"}
            return [l for l in lines if l not in skip and not l.startswith("Rasdial") and "成功" not in l]
        except Exception:
            return []

    def flush_dns(self) -> bool:
        if os.name != "nt": return False
        try:
            r = subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=15, creationflags=NO_WINDOW)
            return r.returncode == 0
        except Exception:
            return False

    def start_exe(self, path: str) -> int | None:
        """启动主程序，返回新 pid（尽力）；失败返回 None。"""
        if not path or not os.path.isfile(path): return None
        try:
            # 不抢控制台；Detached
            flags = NO_WINDOW
            if hasattr(subprocess, "DETACHED_PROCESS"): flags |= subprocess.DETACHED_PROCESS
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"): flags |= subprocess.CREATE_NEW_PROCESS_GROUP
            p = subprocess.Popen([path], cwd=str(Path(path).parent), creationflags=flags,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            return p.pid
        except Exception:
            return None

    def stop_pid(self, pid: int) -> bool:
        if not self.ps or not pid: return False
        try:
            self.ps.Process(pid).terminate(); return True
        except Exception:
            return False

    def rasdial_connect(self, name: str) -> bool:
        try:
            r = subprocess.run(["rasdial", name], capture_output=True, timeout=60, creationflags=NO_WINDOW)
            return r.returncode == 0
        except Exception:
            return False

    def rasdial_disconnect(self, name: str) -> bool:
        try:
            r = subprocess.run(["rasdial", name, "/disconnect"], capture_output=True, timeout=30, creationflags=NO_WINDOW)
            return r.returncode == 0
        except Exception:
            return False


def parse_proxy_hostport(server: str) -> list[tuple[str, int]]:
    """从 Win ProxyServer 字符串抽出 (host, port)。"""
    out = []
    for part in re.split(r"[;\s]+", server or ""):
        part = part.strip()
        if not part: continue
        if "=" in part: part = part.split("=", 1)[1]
        m = re.match(r"^(?:https?://)?([^:/]+):(\d+)$", part, re.I)
        if m: out.append((m.group(1), int(m.group(2))))
    return out


def known_install_globs(family: dict) -> list[str]:
    """只查有限的已知候选路径，绝不整盘 walk。"""
    la = os.path.expandvars("%LOCALAPPDATA%")
    ra = os.path.expandvars("%APPDATA%")
    pf = os.path.expandvars("%ProgramFiles%")
    pfx = os.path.expandvars("%ProgramFiles(x86)%")
    home = os.path.expanduser("~")
    names = list(family.get("exe_names") or [])
    keys = list(family.get("path_keys") or [])
    bases = [
        os.path.join(la, "Programs"),
        la, ra, pf, pfx,
        os.path.join(home, "AppData", "Local", "Programs"),
        r"D:\ClashVergeRev", r"D:\Clash", r"D:\v2rayN", r"E:\ClashVergeRev",
        os.path.join(pf, "WireGuard"), os.path.join(pf, "Tailscale"), os.path.join(pf, "OpenVPN"),
        os.path.join(pfx, "OpenVPN"),
    ]
    out = []
    for b in bases:
        if not b or not os.path.isdir(b):
            continue
        for en in names:
            out.append(os.path.join(b, en))
        # one level of subdirs matching path_keys
        try:
            for name in os.listdir(b):
                low = name.lower()
                if any(k in low for k in keys):
                    for en in names:
                        out.append(os.path.join(b, name, en))
        except OSError:
            pass
    return out


def find_start_exe(family: dict, running_exes: list[str]) -> tuple[str, str]:
    """返回 (install_path, start_exe)。优先正在跑的主程序路径，再查已知候选，不整盘扫描。"""
    for e in running_exes:
        low = (e or "").lower().replace("/", chr(92))
        name = Path(e).name.lower()
        if any(x.lower() == name for x in family["exe_names"]) or family["proc"].search(e or ""):
            if "service" in name or "mihomo" in name or "core" in low:
                continue
            return str(Path(e).parent), e
    for e in running_exes:
        p = Path(e)
        for parent in [p.parent, *list(p.parents)[:4]]:
            for en in family["exe_names"]:
                cand = parent / en
                if cand.is_file():
                    return str(parent), str(cand)
    for cand in known_install_globs(family):
        if os.path.isfile(cand):
            return str(Path(cand).parent), cand
    return "", ""


def detect_vpn_clients(view: RealNetView) -> list[VpnClient]:
    rows = view.procs_blob()
    ports = view.listen_ports_by_pid()
    found = []
    for fam in VPN_FAMILIES:
        pids, exes = [], []
        for pid, name, exe, cmd in rows:
            blob = f"{name} {exe} {cmd}"
            if fam["proc"].search(blob):
                # 过滤误伤：Edge WebView 命令行里偶尔带 clash 字样
                if "msedgewebview" in name.lower() or "msedgewebview" in (exe or "").lower():
                    continue
                if "python" in name.lower() and "clash" not in (exe or "").lower() and "clash" not in cmd.lower():
                    # 本探测脚本自己
                    if "network" in cmd.lower() or "dry_run" in cmd.lower(): continue
                pids.append(pid); 
                if exe: exes.append(exe)
        install, start = find_start_exe(fam, exes)
        # 没在跑也尝试找安装
        if not start:
            install2, start2 = find_start_exe(fam, [])
            install = install or install2; start = start or start2
        if not pids and not start: continue
        lp = sorted({p for pid in pids for p in ports.get(pid, [])})
        found.append(VpnClient(fam["id"], fam["labels"][0], bool(pids), pids, list(dict.fromkeys(exes)), install, start, lp))
    return found


class NetworkKit:
    def __init__(self, view, home: Path, clock=time.time, hosts=None, sleep=time.sleep, log=lambda *a: None):
        self.view, self.home, self.clock, self.sleep, self.log = view, Path(home), clock, sleep, log
        self.hosts = list(hosts or DEFAULT_HOSTS)
        self.seen_file = self.home / "network_seen_clients.json"
        self.journal = self.home / "network_journal.jsonl"
        self.home.mkdir(parents=True, exist_ok=True)
        self._last_probe: list[ProbeResult] = []
        self._acted: set[str] = set()          # 本轮已尝试过的动作键，避免疯狂重试同一步

    def _load_seen(self) -> dict:
        try: return json.loads(self.seen_file.read_text("utf-8"))
        except Exception: return {}

    def _save_seen(self, d: dict):
        self.seen_file.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")

    def remember_running(self, clients: list[VpnClient]):
        d = self._load_seen()
        now = self.clock()
        for c in clients:
            if c.running and c.start_exe:
                d[c.family] = dict(label=c.label, start_exe=c.start_exe, install=c.install_path,
                                   last_seen=now, listen_ports=c.listen_ports)
        self._save_seen(d)

    def probe_hosts(self) -> list[ProbeResult]:
        out = []
        for h in self.hosts:
            pr = ProbeResult(h["host"], h.get("tag", ""))
            if h.get("skip_dns"):
                pr.dns_ok, pr.dns_addrs = True, [h["host"]]
            else:
                pr.dns_ok, pr.dns_addrs, pr.dns_err = self.view.resolve(h["host"])
            target = pr.dns_addrs[0] if pr.dns_addrs and not h.get("skip_dns") else h["host"]
            # 对域名：用原主机名连，让 SNI/系统栈正常；IP 直接连
            connect_host = h["host"] if not h.get("skip_dns") else h["host"]
            if pr.dns_ok or h.get("skip_dns"):
                pr.tcp_ok, pr.tcp_ms, pr.tcp_err = self.view.tcp443(connect_host)
            else:
                pr.tcp_err = "dns_failed"
            out.append(pr)
        self._last_probe = out
        return out

    def snapshot(self) -> dict:
        probes = self.probe_hosts()
        clients = detect_vpn_clients(self.view)
        self.remember_running(clients)
        proxy = self.view.system_proxy()
        route_ok = self.view.default_route()
        win_vpns = self.view.win_vpns()
        ras = self.view.rasdial_status()
        proxy_ports = parse_proxy_hostport(proxy.get("server") or "")
        dead_ports = []
        for host, port in proxy_ports:
            if host in ("127.0.0.1", "localhost", "::1") and not self.view.port_listening(port):
                dead_ports.append(port)
        return dict(probes=probes, clients=clients, proxy=proxy, route_ok=route_ok,
                    win_vpns=win_vpns, rasdial=ras, dead_proxy_ports=dead_ports, seen=self._load_seen())

    def discover(self, w) -> list:
        snap = self.snapshot()
        probes, clients = snap["probes"], snap["clients"]
        fail = [p for p in probes if not p.tcp_ok]
        dns_fail = [p for p in probes if not p.dns_ok and p.tag != "ip"]
        signals = {}
        reasons = []
        if not snap["route_ok"]:
            signals["no_route"] = True; reasons.append("无默认路由")
        if len(fail) >= max(2, (len(probes) + 1) // 2):
            signals["hosts_unreachable"] = len(fail); reasons.append(f"{len(fail)}/{len(probes)} 主机 443 不通")
        if dns_fail and len(dns_fail) >= 2:
            signals["dns_fail"] = len(dns_fail); reasons.append(f"{len(dns_fail)} 个域名解析失败")
        if snap["dead_proxy_ports"]:
            signals["proxy_dead"] = snap["dead_proxy_ports"]; reasons.append(f"系统代理端口未监听 {snap['dead_proxy_ports']}")
        # 曾见过在跑的客户端，现在不在跑，且有任一失败或代理死
        seen = snap["seen"]; down = []
        running_ids = {c.family for c in clients if c.running}
        for fam, info in seen.items():
            if fam not in running_ids and info.get("start_exe"):
                down.append(fam)
        if down and (signals.get("hosts_unreachable") or signals.get("proxy_dead") or signals.get("dns_fail")):
            signals["vpn_client_down"] = down; reasons.append("本地代理/VPN 客户端曾在跑现已退出：" + ",".join(down))
        # 国外全挂、国内还行，且有已装客户端未连 / 系统 VPN 断开
        foreign_fail = all(not p.tcp_ok for p in probes if p.tag == "foreign")
        domestic_ok = any(p.tcp_ok for p in probes if p.tag == "domestic")
        if foreign_fail and domestic_ok:
            signals["foreign_blocked"] = True; reasons.append("国外站点不通、国内还通")
            disconnected = [v.name for v in snap["win_vpns"] if str(v.status).lower() != "connected"]
            if disconnected: signals["win_vpn_disconnected"] = disconnected
            # 客户端在跑但国外仍不通：不急着重启，留给 flushdns/理解；客户端未跑且装过：标记
            if down or (any(not c.running and c.start_exe for c in clients)):
                signals.setdefault("vpn_client_down", down or [c.family for c in clients if not c.running and c.start_exe])

        if not reasons:
            return []
        title = "网络不可达：" + "；".join(reasons[:3])
        sev = 0.7 if signals.get("no_route") or signals.get("hosts_unreachable") else 0.5
        return [Candidate("network_break", "net:break", title,
                          dict(severity=sev, need=1.0, unit="处", **{k: v for k, v in signals.items() if k not in ("severity", "need", "unit")}),
                          dict(snapshot=snap, reasons=reasons))]

    def gather(self, c, facts, world, view):
        snap = c.ctx.get("snapshot") or self.snapshot()
        ev = []
        probes = snap["probes"]
        for p in probes:
            if p.dns_ok:
                ev.append(f"DNS {p.host} → {','.join(p.dns_addrs[:3]) or '?'}；TCP443 {'OK' if p.tcp_ok else 'FAIL'} {p.tcp_ms:.0f}ms")
            else:
                ev.append(f"DNS {p.host} FAIL {p.dns_err}")
        facts["probe_ok"] = sum(1 for p in probes if p.tcp_ok)
        facts["probe_n"] = len(probes)
        facts["route_ok"] = snap["route_ok"]; ev.append("默认路由：" + ("有" if snap["route_ok"] else "无"))
        px = snap["proxy"]
        facts["proxy"] = px
        ev.append(f"系统代理 enable={px.get('enable')} server={px.get('server') or '-'} pac={px.get('pac') or '-'}")
        if snap["dead_proxy_ports"]:
            facts["proxy_dead_ports"] = snap["dead_proxy_ports"]; ev.append(f"代理端口未监听：{snap['dead_proxy_ports']}")
        clients = snap["clients"]
        facts["clients"] = [dict(family=x.family, label=x.label, running=x.running, start_exe=x.start_exe,
                                 ports=x.listen_ports, install=x.install_path) for x in clients]
        if clients:
            ev.append("本地代理/VPN 客户端：" + "；".join(
                f"{x.label}({'在跑' if x.running else '未跑'}; ports={x.listen_ports or '-'}; exe={Path(x.start_exe).name if x.start_exe else '-'})"
                for x in clients))
        else:
            ev.append("未发现已装/在跑的常见本地代理/VPN 客户端")
        facts["seen"] = snap["seen"]
        wv = snap["win_vpns"]; facts["win_vpns"] = [dict(name=v.name, status=v.status, server=v.server) for v in wv]
        if wv: ev.append("Windows VPN：" + "；".join(f"{v.name}={v.status}" for v in wv))
        else: ev.append("没有已配置的 Windows VPN 连接")
        if snap["rasdial"]: facts["rasdial"] = snap["rasdial"]; ev.append("rasdial 已连接：" + ",".join(snap["rasdial"]))
        # 归因
        cause = "unknown"
        if not snap["route_ok"]: cause = "no_route"
        elif snap["dead_proxy_ports"] or c.signals.get("vpn_client_down") or c.signals.get("proxy_dead"):
            cause = "proxy_or_client_down"
        elif c.signals.get("dns_fail") and facts["probe_ok"] == 0: cause = "dns"
        elif c.signals.get("foreign_blocked") or c.signals.get("win_vpn_disconnected"): cause = "need_vpn"
        elif c.signals.get("hosts_unreachable"): cause = "connectivity"
        facts["cause"] = cause
        facts["what"] = f"网络异常（{cause}）：" + "；".join(c.ctx.get("reasons") or [])
        facts["owner"] = "system-network"
        return ev

    def judge(self, c, facts) -> Understanding:
        """本地只整理白名单线索；问题定性留给 novel（prefer_novel）。
        无 novel 时仍可按线索给出可逆 act，作为预算降级回退。"""
        u = Understanding(c.key, c.kind, c.title, what=facts.get("what", ""), owner=facts.get("owner", ""))
        cause = facts.get("cause", "unknown")
        clients = facts.get("clients") or []
        seen = facts.get("seen") or {}
        win_vpns = facts.get("win_vpns") or []
        can_flush = True
        restartable = []
        for fam, info in seen.items():
            if info.get("start_exe") and not any(x["family"] == fam and x["running"] for x in clients):
                restartable.append(dict(family=fam, **info))
        for x in clients:
            if (not x["running"]) and x.get("start_exe") and x["family"] in seen:
                restartable.append(dict(family=x["family"], label=x["label"], start_exe=x["start_exe"], install=x.get("install"), last_seen=seen.get(x["family"], {}).get("last_seen")))
        seen_f = set(); rr = []
        for r in restartable:
            if r["family"] in seen_f: continue
            seen_f.add(r["family"]); rr.append(r)
        restartable = rr
        disconnected = [v for v in win_vpns if str(v.get("status", "")).lower() != "connected"]
        facts["restartable"] = restartable
        facts["disconnected_vpns"] = disconnected
        facts["whitelist_hints"] = dict(cause=cause, can_flush=can_flush,
                                        restartable_n=len(restartable), disconnected_n=len(disconnected))

        # 默认定性 unknown，让 novel 说「这是什么」；仅在有明确白名单路径时 act（执行器回退）
        u.state, u.confidence = "unknown", 0.45
        if cause == "no_route":
            u.why = "传感器：无默认路由；无线索可逆动作"
            return u
        if restartable and cause in ("proxy_or_client_down", "need_vpn", "connectivity", "dns"):
            u.act, u.confidence = True, 0.78  # >= Engine min_conf；state 仍 unknown 交给 novel 定性
            u.why = f"白名单线索：可逆拉起曾用客户端 {','.join(r['family'] for r in restartable)}"
            return u
        if disconnected and cause in ("need_vpn", "connectivity", "foreign_blocked", "dns"):
            u.act, u.confidence = True, 0.78
            u.why = f"白名单线索：rasdial 已有 VPN {','.join(v['name'] for v in disconnected)}"
            return u
        if cause in ("dns", "connectivity", "proxy_or_client_down") and can_flush:
            u.act, u.confidence = True, 0.76
            u.why = "白名单线索：可 flushdns"
            return u
        u.why = "传感器有异常但无线索可逆动作"
        return u

    def recheck(self, c, w) -> float:
        probes = self.probe_hosts()
        ok = sum(1 for p in probes if p.tcp_ok)
        # 过半可达即解除
        if ok >= max(2, (len(probes) + 1) // 2):
            return 0.0
        return float(c.signals.get("need", 1.0))

    def propose(self, c, u, w) -> list:
        facts = u.facts or {}
        acts = []
        kit = self
        # 1) flushdns
        if "flushdns" not in self._acted:
            def dry_f(): return True
            def run_f():
                ok = kit.view.flush_dns(); kit._acted.add("flushdns")
                kit.journal.open("a", encoding="utf-8").write(json.dumps(dict(ts=kit.clock(), kind="flushdns", ok=ok)) + "\\n")
                return dict(ok=ok)
            def ver_f(r): return True  # flush 本身总“成功”；是否解除由 recheck 定
            def undo_f(r): pass
            acts.append(Action("net_flushdns", "刷新 DNS 缓存", "low", "full", relief=0.3, reason=u.why, confident=True, value_s=120.0,
                               dry_run=dry_f, run=run_f, verify=ver_f, undo=undo_f,
                               done_text=lambda xs: "已刷新 DNS 缓存（ipconfig /flushdns）",
                               done_short=lambda xs: "已刷新 DNS"))
        # 2) restart clients
        for rinfo in facts.get("restartable") or []:
            key = "restart:" + rinfo["family"]
            if key in self._acted: continue
            exe = rinfo.get("start_exe") or ""
            fam = rinfo["family"]; label = rinfo.get("label") or fam
            def dry_r(exe=exe): return bool(exe) and os.path.isfile(exe)
            def run_r(exe=exe, fam=fam, key=key, label=label):
                pid = kit.view.start_exe(exe)
                if not pid: raise RuntimeError(f"无法启动 {exe}")
                kit._acted.add(key)
                kit.sleep(2.0)
                kit.journal.open("a", encoding="utf-8").write(json.dumps(dict(ts=kit.clock(), kind="restart_client", family=fam, exe=exe, pid=pid)) + "\\n")
                return dict(family=fam, exe=exe, pid=pid, label=label)
            def ver_r(r, fam=fam):
                # 启动后稍等，看该族是否出现在跑 / 或网络开始恢复
                kit.sleep(1.0)
                clients = detect_vpn_clients(kit.view)
                if any(x.family == fam and x.running for x in clients): return True
                # 或者监视主机已经好了也算
                return kit.recheck(c, w) == 0.0
            def undo_r(r):
                if r and r.get("pid"): kit.view.stop_pid(r["pid"])
            acts.append(Action("net_restart_client", f"重新拉起 {label}", "medium", "full", relief=0.8, reason=u.why, confident=True, value_s=600.0,
                               dry_run=dry_r, run=run_r, verify=ver_r, undo=undo_r,
                               done_text=lambda xs, label=label: f"已重新拉起本地代理/VPN 客户端 {label}（可撤销：结束我启动的进程）",
                               done_short=lambda xs, label=label: f"已拉起 {label}"))
        # 3) rasdial
        for v in facts.get("disconnected_vpns") or []:
            name = v["name"]; key = "rasdial:" + name
            if key in self._acted: continue
            def dry_v(name=name): return True
            def run_v(name=name, key=key):
                ok = kit.view.rasdial_connect(name)
                if not ok: raise RuntimeError(f"rasdial {name} 失败")
                kit._acted.add(key)
                kit.journal.open("a", encoding="utf-8").write(json.dumps(dict(ts=kit.clock(), kind="rasdial_connect", name=name)) + "\\n")
                return dict(name=name, prior="Disconnected")
            def ver_v(r, name=name):
                connected = name in kit.view.rasdial_status() or any(x.name == name and str(x.status).lower() == "connected" for x in kit.view.win_vpns())
                return connected or kit.recheck(c, w) == 0.0
            def undo_v(r):
                if r and r.get("name"): kit.view.rasdial_disconnect(r["name"])
            acts.append(Action("net_rasdial", f"连接 VPN {name}", "medium", "full", relief=0.9, reason=u.why, confident=True, value_s=900.0,
                               dry_run=dry_v, run=run_v, verify=ver_v, undo=undo_v,
                               done_text=lambda xs, name=name: f"已用 rasdial 连接 Windows VPN「{name}」（撤销会断开）",
                               done_short=lambda xs, name=name: f"已连接 VPN {name}"))
        # Engine 会按价值选；我们把最有可能的放前面。若多条，只返回按优先级截断到 1 条，让 open-until-resolved 下一轮再试下一项
        return acts[:1] if acts else []


def throttled(fn, secs, clock=time.time):
    st = dict(t=-1e18, v=[])
    def f(w):
        if clock() - st["t"] >= secs: st["v"] = fn(w); st["t"] = clock()
        return st["v"]
    return f


def register_all(ireg: InvestigatorRegistry, kit: NetworkKit | None, clock=time.time, poll_s=20.0):
    register_generic(ireg)
    if kit:
        ireg.discoverer("network_break", throttled(kit.discover, poll_s, clock))
        ireg.gatherer("network_evidence", lambda c: c.kind == "network_break", kit.gather)
        ireg.judge("network_break", kit.judge)
        ireg.responder("network_break", kit.propose, kit.recheck)
    return ireg


def build(home: Path, live=False, apply_real=False, log=print, view=None, clock=time.time, hosts=None, poll_s=20.0,
          novel=None, novel_from_env=False):
    home = Path(home); view = view or RealNetView()
    ireg = InvestigatorRegistry()
    kit = NetworkKit(view, home, clock, hosts=hosts, log=log)
    register_all(ireg, kit, clock, poll_s=poll_s)
    if novel is None and novel_from_env:
        from ..novel import NovelUnderstander
        novel = NovelUnderstander.from_env(home, clock=clock, log=log)
    inv = Investigator(ireg, view, home, clock, log, novel=novel)
    sc = investigator_scenario(ireg, inv, live=bool(live and apply_real), log=log, name="investigate_network")
    return sc, dict(kit=kit, inv=inv, ireg=ireg, novel=novel)
