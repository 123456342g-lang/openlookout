"""只读自检：本机 Langflow / Ollama 版本是否落在已公开安全公告的受影响范围内，以及 Ollama 是否对外监听。
不改任何东西、不上传任何东西。需要 Python 3.8+，零依赖。
用法：
  python check_ai_tools.py                      # 用同目录 advisories.json（打包时的快照）
  python check_ai_tools.py --online             # 先从 GitHub 公告库刷新 Langflow 公告
  python check_ai_tools.py --langflow-url http://127.0.0.1:7860 --ollama-url http://127.0.0.1:11434
退出码：0 = 没发现问题；1 = 有需要升级/处理的项；2 = 没检测到任何服务（请先启动应用再查）"""
import argparse, json, os, re, shutil, socket, subprocess, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGFLOW_PORTS = [7860, 7861, 7862, 7868, 3000]

def vtuple(v):
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", str(v).strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None

def in_range(v, rng):
    """rng 形如 '>= 1.7.0, < 1.10.1' / '<= 1.10.0' / '< 1.10.3'（GitHub 公告格式）"""
    vt = vtuple(v)
    for part in [p.strip() for p in rng.split(",") if p.strip()]:
        op, ver = re.match(r"(>=|<=|>|<|=)?\s*(.+)", part).groups()
        t = vtuple(ver); op = op or "="
        ok = {">=": vt >= t, "<=": vt <= t, ">": vt > t, "<": vt < t, "=": vt == t}[op]
        if not ok: return False
    return True

def get_json(url, timeout=3):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lookout-check"}), timeout=timeout) as r:
        return json.loads(r.read().decode())

def refresh_advisories(path):
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    items = get_json("https://api.github.com/advisories?affects=langflow&per_page=50&sort=published", timeout=20)
    data["langflow"] = [{"ghsa": a["ghsa_id"], "cve": a["cve_id"], "published": a["published_at"][:10], "severity": a["severity"],
                         "summary": a["summary"], "url": a["html_url"],
                         "ranges": [(v["vulnerable_version_range"], v["first_patched_version"]) for v in a["vulnerabilities"] if v["package"]["name"] == "langflow"]}
                        for a in items if not a["summary"].startswith("Duplicate Advisory")]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data

def find_langflow(url):
    cands = [url] if url else [f"http://127.0.0.1:{p}" for p in LANGFLOW_PORTS]
    for u in cands:
        try:
            d = get_json(u.rstrip("/") + "/api/v1/version")
            if "version" in d: return u, d
        except Exception:
            pass
    return None, None

def find_ollama(url):
    u = url or os.environ.get("OLLAMA_HOST_CHECK") or "http://127.0.0.1:11434"
    try:
        return u, get_json(u.rstrip("/") + "/api/version")["version"], "api"
    except Exception:
        pass
    exe = shutil.which("ollama")
    if exe:
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout + ""
            m = re.search(r"(\d+\.\d+\.\d+)", out)
            if m: return None, m.group(1), "cli"
        except Exception:
            pass
    return None, None, None

def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ips.add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    return [i for i in ips if not i.startswith("127.")]

def ollama_exposure(port=11434):
    env = os.environ.get("OLLAMA_HOST", "")
    exposed = [ip for ip in lan_ips() if _open(ip, port)]
    return env, exposed

def _open(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=1): return True
    except Exception:
        return False

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true"); ap.add_argument("--langflow-url"); ap.add_argument("--ollama-url")
    ap.add_argument("--advisories", default=str(HERE / "advisories.json")); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    p = Path(a.advisories)
    adv = refresh_advisories(p) if a.online else json.loads(p.read_text(encoding="utf-8"))
    report, problems, found = [], 0, 0
    # Langflow
    u, info = find_langflow(a.langflow_url)
    if info:
        found += 1; v = info.get("main_version") or info["version"]
        hits = [x for x in adv["langflow"] if any(in_range(v, r) for r, _ in x["ranges"])]
        need = max((vtuple(fx) for x in hits for r, fx in x["ranges"] if fx and in_range(v, r)), default=None)
        report.append({"tool": "Langflow", "where": u, "version": v, "advisories": [f'{x["cve"] or x["ghsa"]} ({x["severity"]})' for x in hits],
                       "verdict": "需要升级" if hits else "未落在快照中的受影响范围",
                       "min_fixed": ".".join(map(str, need)) if need else None, "latest_known": adv.get("langflow_latest")})
        problems += bool(hits)
    else:
        report.append({"tool": "Langflow", "verdict": "未检测到正在运行的 Langflow（请先打开 Langflow Desktop 再运行；或用 --langflow-url 指定）"})
    # Ollama
    u, v, how = find_ollama(a.ollama_url)
    if v:
        found += 1
        o = adv["ollama"]; vulnerable = in_range(v, o["range"]); old = vtuple(v) < vtuple(o["recommended"])
        env, exposed = ollama_exposure()
        report.append({"tool": "Ollama", "version": v, "via": how, "advisory": o["cve"],
                       "verdict": "在公告列出的受影响范围内，需要升级" if vulnerable else ("低于建议版本，建议升级" if old else "版本不低于建议版本"),
                       "recommended": o["recommended"], "OLLAMA_HOST": env or "(未设置，默认只听 127.0.0.1)",
                       "reachable_from_lan_ip": exposed})
        problems += vulnerable or old or bool(exposed)
    else:
        report.append({"tool": "Ollama", "verdict": "未检测到 Ollama（服务没开，且 PATH 里没有 ollama 命令）"})
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for r in report:
            print(f"[{r['tool']}] {r['verdict']}")
            for k, val in r.items():
                if k not in ("tool", "verdict") and val not in (None, [], ""): print(f"    {k}: {val}")
    return 2 if not found else (1 if problems else 0)

if __name__ == "__main__":
    sys.exit(main())
