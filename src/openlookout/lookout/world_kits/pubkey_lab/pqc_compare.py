"""用本机 OpenSSL (>=3.5) 对比经典公钥算法和后量子算法（ML-KEM / ML-DSA）的密钥/密文/签名尺寸和速度。
运行：python pqc_compare.py [--out pqc_compare.md]
Windows 上需要 OpenSSL 3.5+（Git for Windows 自带的版本可能更旧，脚本会报出来）。"""
import argparse, os, re, subprocess, tempfile, shutil

SIG = ["RSA:2048", "RSA:3072", "ED25519", "ML-DSA-44", "ML-DSA-65"]
KEM = ["X25519", "ML-KEM-512", "ML-KEM-768"]

def sh(*a, inp=None):
    return subprocess.run(["openssl", *a], input=inp, capture_output=True, check=True).stdout

def genkey(alg, d):
    name, _, bits = alg.partition(":")
    f = os.path.join(d, alg.replace(":", "_") + ".pem")
    args = ["genpkey", "-algorithm", name, "-out", f] + (["-pkeyopt", f"rsa_keygen_bits:{bits}"] if bits else [])
    sh(*args)
    pub = sh("pkey", "-in", f, "-pubout", "-outform", "DER")
    return f, len(pub)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out"); ap.add_argument("--seconds", default="1")
    a = ap.parse_args()
    ver = sh("version").decode().strip()
    m = re.search(r"OpenSSL (\d+)\.(\d+)", ver)
    if not m or (int(m[1]), int(m[2])) < (3, 5): raise SystemExit(f"需要 OpenSSL 3.5+，当前：{ver}")
    d = tempfile.mkdtemp(); rows = []
    msg = os.path.join(d, "msg.bin"); open(msg, "wb").write(b"lab7" * 64)
    try:
        for alg in SIG:
            f, pub = genkey(alg, d)
            sig = os.path.join(d, "sig.bin")
            sh("pkeyutl", "-sign", "-rawin", "-inkey", f, "-in", msg, "-out", sig, *(["-digest", "sha256"] if alg.startswith("RSA") else []))
            ok = subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-inkey", f, "-in", msg, "-sigfile", sig,
                                 *(["-digest", "sha256"] if alg.startswith("RSA") else [])], capture_output=True).returncode == 0
            rows.append(("签名", alg, pub, os.path.getsize(sig), ok))
        for alg in KEM:
            f, pub = genkey(alg, d)
            if alg.startswith("ML-KEM"):
                ct, ss = os.path.join(d, "ct.bin"), os.path.join(d, "ss.bin")
                pubf = os.path.join(d, "pub.pem"); sh("pkey", "-in", f, "-pubout", "-out", pubf)
                sh("pkeyutl", "-encap", "-pubin", "-inkey", pubf, "-out", ct, "-secret", ss)
                ss2 = os.path.join(d, "ss2.bin"); sh("pkeyutl", "-decap", "-inkey", f, "-in", ct, "-secret", ss2)
                rows.append(("KEM", alg, pub, os.path.getsize(ct), open(ss, "rb").read() == open(ss2, "rb").read()))
            else:
                rows.append(("KEM", alg, pub, pub - 12, True))   # X25519 的"密文"就是对方 32 字节公钥
        speed = subprocess.run(["openssl", "speed", "-seconds", a.seconds, "rsa2048", "ed25519", "ML-DSA-44", "ML-DSA-65", "ML-KEM-768", "X25519"],
                               capture_output=True, text=True).stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)
    out = [f"# 经典 vs 后量子：尺寸与速度（{ver}）", "", "| 类型 | 算法 | 公钥 DER 字节 | 签名/密文字节 | 往返自检 |", "|---|---|---|---|---|"]
    out += [f"| {t} | {alg} | {pub} | {sz} | {'通过' if ok else '失败'} |" for t, alg, pub, sz, ok in rows]
    out += ["", "## openssl speed 原始输出（本机，单线程）", "```", "\n".join(l for l in speed.splitlines() if re.search(r"bits|X25519|ML-|keygen|sign|rsa", l)), "```"]
    text = "\n".join(out); print(text)
    if a.out: open(a.out, "w", encoding="utf-8").write(text)
    if not all(r[4] for r in rows): raise SystemExit(1)

if __name__ == "__main__":
    main()
