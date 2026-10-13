"""干跑：真实探针网络/VPN，只调查、写理解记录，不 flushdns / 不连 VPN / 不重启客户端。
python -m sprite.demo_live.dry_run_network [--home DIR]"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from ..scenarios import network as N
from ..investigate import Candidate
from .common import home_dir


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--home"); a = ap.parse_args(argv)
    home = Path(a.home) if a.home else home_dir(); home.mkdir(parents=True, exist_ok=True)
    sc, kit = N.build(home, live=False, apply_real=False, log=lambda *x: print(*x, flush=True), poll_s=0)
    nk, inv = kit["kit"], kit["inv"]
    print("== 真实网络探针（不动手）==", flush=True)
    snap = nk.snapshot()
    for p in snap["probes"]:
        if p.dns_ok:
            print(f"  {p.host} ({p.tag}): DNS {','.join(p.dns_addrs[:2])} TCP443={'OK' if p.tcp_ok else 'FAIL'} {p.tcp_ms:.0f}ms")
        else:
            print(f"  {p.host} ({p.tag}): DNS FAIL {p.dns_err}")
    print("  默认路由:", "有" if snap["route_ok"] else "无")
    px = snap["proxy"]
    print(f"  系统代理 enable={px.get('enable')} server={px.get('server') or '-'} dead_ports={snap['dead_proxy_ports']}")
    if snap["clients"]:
        for c in snap["clients"]:
            print(f"  客户端 {c.label}: running={c.running} ports={c.listen_ports} start={c.start_exe or '-'} install={c.install_path or '-'}")
    else:
        print("  未发现常见本地代理/VPN 客户端")
    print("  曾见过在跑:", json.dumps(snap["seen"], ensure_ascii=False)[:300])
    if snap["win_vpns"]:
        for v in snap["win_vpns"]:
            print(f"  Windows VPN {v.name}: {v.status} @ {v.server}")
    else:
        print("  无 Windows VPN 配置")
    print("  rasdial 已连接:", snap["rasdial"] or "(无)")
    print("== 发现器 ==", flush=True)
    cands = nk.discover(None)
    if not cands:
        print("当前未发现网络不可达问题（站点大多可达）。若以后挂了，会按理解记录优先：flushdns → 重启曾在跑的本地代理 → rasdial 已有系统 VPN。")
        # 仍写一条健康理解，便于你看见机制在跑
        c = Candidate("network_break", "net:healthcheck", "网络健康检查", dict(severity=0.1, need=0.0, unit="处"), dict(snapshot=snap, reasons=["健康检查"]))
        # 强制走 gather+judge 但不要求 act
        facts = {}; ev = nk.gather(c, facts, None, nk.view)
        u = nk.judge(c, facts); u.evidence = ev; u.act = False; u.why = "当前可达，无需动手"; u.confidence = 0.9
        inv.home.mkdir(parents=True, exist_ok=True)
        with inv.file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(u.to_dict(), ensure_ascii=False, default=str) + "\n")
        print("理解：", u.line())
        for e in u.evidence: print("   ·", e)
        if snap["clients"]:
            print("→ 若站点不通且客户端退出：会可逆地重新拉起", ", ".join(c.label for c in snap["clients"] if c.start_exe))
        if snap["seen"]:
            print("→ seen 客户端:", ", ".join(snap["seen"]))
    else:
        for c in cands:
            u = inv.investigate(c, None, force=True)
            print("-", u.line())
            for e in u.evidence: print("   ·", e)
            if u.act:
                print("   → 干跑计划：", u.why)
    print("记录文件：", inv.file)


if __name__ == "__main__":
    main()
