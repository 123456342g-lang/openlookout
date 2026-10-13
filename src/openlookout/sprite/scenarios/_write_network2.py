# -*- coding: utf-8 -*-
from pathlib import Path
import re
p = Path(r"E:\OpenLookout\src\openlookout\sprite\scenarios\network.py")
t = p.read_text(encoding="utf-8")

# Fix winreg path (double-escaped raw string)
t = t.replace(
    r'r"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Internet Settings"',
    r'r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"',
)

# Extend system_proxy to include override
old_proxy = '''    def system_proxy(self) -> dict:
        out = dict(env_http=os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "",
                   env_https=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "",
                   enable=False, server="", pac="")
        if os.name != "nt": return out
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
'''

new_proxy = '''    def system_proxy(self) -> dict:
        out = dict(env_http=os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "",
                   env_https=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "",
                   enable=False, server="", pac="", override="")
        if os.name != "nt": return out
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings")
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
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings", 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
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
'''

# After fix, the path in file should already be single-backslash from our replace.
# Match whatever is currently there for system_proxy
m = re.search(r"    def system_proxy\(self\) -> dict:.*?return out\n", t, flags=re.S)
if not m:
    raise SystemExit("system_proxy not found")
if "def http_get" not in t:
    t = t[:m.start()] + new_proxy + t[m.end():]
    print("inserted http_get/set_system_proxy")
else:
    print("http_get already present")

p.write_text(t, encoding="utf-8")
print("phase2 lines", len(t.splitlines()))
# verify winreg path
for i,l in enumerate(t.splitlines(),1):
    if "Internet Settings" in l:
        print(i, repr(l[:100]))