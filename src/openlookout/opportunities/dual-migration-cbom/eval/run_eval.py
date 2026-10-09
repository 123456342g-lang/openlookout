"""在真实公开仓库上跑 dmcbom，并和 sonar-cryptography（CBOMkit）README 声明的覆盖范围对照。
用法：python3 eval/run_eval.py [--workdir /tmp/dmcbom_eval]   （仓库浅克隆到 workdir，不进 git）"""
import argparse, json, os, subprocess, sys, time
from collections import Counter, defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import dmcbom

def documented_cbomkit_coverage(lib):
    """sonar-cryptography README（commit 58eea48, 2026-10-08）声明覆盖：Java JCA、BouncyCastle 轻量 API、
    Python pyca/cryptography、Go 标准库 crypto（不含 crypto/x509）、x/crypto 的 hkdf/pbkdf2/sha3。"""
    if lib.startswith("JCA") or lib.startswith("org.bouncycastle") or lib == "pyca" or lib.startswith("pyca("): return True
    if lib.startswith("go:crypto/") and lib != "go:crypto/x509": return True
    if lib in ("go:golang.org/x/crypto/pbkdf2", "go:golang.org/x/crypto/sha3"): return True
    return False

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workdir", default="/tmp/dmcbom_eval"); a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    repos = [l.strip() for l in open(os.path.join(HERE, "repos.txt")) if l.strip() and not l.startswith("#")]
    rows, allf = [], []
    for r in repos:
        d = os.path.join(a.workdir, r.replace("/", "__"))
        if not os.path.isdir(d):
            subprocess.run(["git", "clone", "-q", "--depth", "1", f"https://github.com/{r}", d], check=False, timeout=600)
        if not os.path.isdir(d): rows.append({"repo": r, "error": "clone failed"}); continue
        sha = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        t = time.time(); fs, st = dmcbom.scan_repo(d); dt = time.time() - t
        cbom = dmcbom.to_cbom(fs, r, sha); errs = dmcbom.validate_cbom(cbom)
        for f in fs: f["repo"] = r
        allf += fs
        gm = [f for f in fs if dmcbom.ALG[f["alg"]][1]]
        rows.append({"repo": r, "commit": sha[:12], "files_scanned": sum(v for k, v in st.items() if k.startswith("files_")),
                     "findings": len(fs), "gm_findings": len(gm),
                     "gm_outside_cbomkit_coverage": sum(1 for f in gm if not documented_cbomkit_coverage(f["lib"])),
                     "all_outside_cbomkit_coverage": sum(1 for f in fs if not documented_cbomkit_coverage(f["lib"])),
                     "algs": dict(Counter(f["alg"] for f in fs).most_common()),
                     "usage": dict(Counter(f["usage"] for f in fs)),
                     "gm_calls": sum(1 for f in gm if f["usage"] == "call"),
                     "gm_calls_outside_cbomkit_coverage": sum(1 for f in gm if f["usage"] == "call" and not documented_cbomkit_coverage(f["lib"])),
                     "verdicts": dict(Counter(dmcbom.verdict(f["alg"])[0] for f in fs)),
                     "libs": dict(Counter(f["lib"] for f in fs).most_common()),
                     "cbom_schema_errors": len(errs), "seconds": round(dt, 2)})
        print(rows[-1]["repo"], rows[-1]["findings"], rows[-1]["gm_findings"], rows[-1]["gm_outside_cbomkit_coverage"], "schema_err", len(errs))
    json.dump({"rows": rows}, open(os.path.join(HERE, "results.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(allf, open(os.path.join(a.workdir, "all_findings.json"), "w"), ensure_ascii=False)
    tot = lambda k: sum(r.get(k, 0) for r in rows)
    L = ["# dmcbom 真实仓库实测（自动生成）", "", f"运行时间：{time.strftime('%Y-%m-%d %H:%M')}（UTC+8）；仓库为浅克隆的默认分支 HEAD。", "",
         "| 仓库 | commit | 扫描文件 | 发现 | 其中调用点 | 国密发现 | 国密调用点 | 国密且不在 CBOMkit 文档覆盖内 | Schema |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r: L.append(f"| {r['repo']} | 克隆失败 | | | | | | | |"); continue
        L.append(f"| {r['repo']} | {r['commit']} | {r['files_scanned']} | {r['findings']} | {r['usage'].get('call', 0)} | {r['gm_findings']} | {r['gm_calls']} | {r['gm_outside_cbomkit_coverage']} | {'通过' if r['cbom_schema_errors'] == 0 else r['cbom_schema_errors']} |")
    L.append(f"| **合计** | | {tot('files_scanned')} | {tot('findings')} | {sum(r.get('usage', {}).get('call', 0) for r in rows)} | {tot('gm_findings')} | {tot('gm_calls')} | {tot('gm_outside_cbomkit_coverage')} | |")
    L += ["", "“不在 CBOMkit 文档覆盖内”= 该发现来自的库不在 sonar-cryptography README 声明的覆盖表里（JCA、BouncyCastle 轻量 API、pyca、Go 标准库）。"
          "这是按文档推断，**没有实际运行 SonarQube 对照**。"]
    open(os.path.join(HERE, "RESULTS.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("TOTAL findings", tot("findings"), "gm", tot("gm_findings"), "gm outside cbomkit", tot("gm_outside_cbomkit_coverage"),
          "all outside", tot("all_outside_cbomkit_coverage"))

if __name__ == "__main__":
    main()
