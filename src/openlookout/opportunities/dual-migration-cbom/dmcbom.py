#!/usr/bin/env python3
"""dmcbom —「国密 × 抗量子」双迁移密码资产清单（源码级 CBOM）。

为什么要有它：中国的系统往往要做两次迁移——
  1) 国密改造：RSA/ECDSA/AES/SHA → SM2/SM3/SM4（密评、等保驱动）；
  2) 抗量子迁移：RSA/ECC 会被 Shor 算法破解；**SM2/SM9 同样基于（椭圆曲线/配对）离散对数**，
     所以国密改造完成后还要再迁一次（国内新一代算法 NGCC 正在征集，国际侧已有 ML-KEM/ML-DSA）。
现有开源 CBOM 扫描器（如 IBM/PQCA 的 sonar-cryptography）按 README 只覆盖 JCA、BouncyCastle、pyca、Go 标准库，
不认识 gmssl（Python）、tjfoc/emmansun gmsm（Go）、sm-crypto（JS）、Hutool SmUtil（Java）、GmSSL/铜锁 C API。

本工具：只用标准库，静态扫描源码（Python 用 AST 解析别名；Go/JS/Java/C 用“导入绑定 + 使用点”匹配），
每条发现同时标两条轴：是否国密、量子影响；输出 CycloneDX 1.6 CBOM（可用官方 schema 校验）和中文迁移清单。

用法：python3 dmcbom.py <repo_dir> [--cbom out.json] [--md out.md] [--json findings.json]
"""
import ast, json, os, re, sys, uuid, argparse
from collections import defaultdict, Counter
from datetime import datetime, timezone

__version__ = "0.1.0"

# --------------------------------------------------------------------------- algorithm catalog
# q: shor = 公钥，Shor 可破；sym = 对称/杂凑，≥128 位按 NIST IR 8547 §4.1.3 判断量子影响有限；
#    legacy = 经典意义上已不推荐；pqc = 抗量子标准；kdf = 口令/密钥派生
ALG = {
    "SM2": ("pke", True, "shor"), "SM9": ("pke", True, "shor"),
    "SM3": ("hash", True, "sym"), "SM4": ("block-cipher", True, "sym"), "ZUC": ("stream-cipher", True, "sym"),
    "RSA": ("pke", False, "shor"), "EC": ("pke", False, "shor"), "ECDSA": ("signature", False, "shor"),
    "ECDH": ("key-agree", False, "shor"), "EdDSA": ("signature", False, "shor"), "X25519": ("key-agree", False, "shor"),
    "DH": ("key-agree", False, "shor"), "DSA": ("signature", False, "shor"), "ElGamal": ("pke", False, "shor"),
    "AES": ("block-cipher", False, "sym"), "ChaCha20": ("stream-cipher", False, "sym"),
    "SHA-2": ("hash", False, "sym"), "SHA-3": ("hash", False, "sym"), "BLAKE2": ("hash", False, "sym"),
    "HMAC": ("mac", False, "sym"), "PBKDF2": ("kdf", False, "kdf"), "scrypt": ("kdf", False, "kdf"),
    "bcrypt": ("kdf", False, "kdf"), "Argon2": ("kdf", False, "kdf"),
    "MD5": ("hash", False, "legacy"), "SHA-1": ("hash", False, "legacy"), "DES": ("block-cipher", False, "legacy"),
    "3DES": ("block-cipher", False, "legacy"), "RC4": ("stream-cipher", False, "legacy"), "RC2": ("block-cipher", False, "legacy"),
    "ML-KEM": ("kem", False, "pqc"), "ML-DSA": ("signature", False, "pqc"), "SLH-DSA": ("signature", False, "pqc"),
}
Q_LABEL = {"shor": "量子：Shor 可破（公钥）", "sym": "量子：影响有限（对称/杂凑）", "legacy": "经典意义上已淘汰",
           "pqc": "已抗量子（NIST 标准）", "kdf": "口令/密钥派生（量子影响有限）"}

def verdict(alg):
    prim, gm, q = ALG[alg]
    if q == "legacy": return "L", "经典意义上已不推荐：两条路线都要先换掉"
    if q == "pqc": return "P", "已是 NIST 抗量子标准；若系统需国密合规，目前尚无对应国密算法（NGCC 征集中）"
    if gm and q == "shor": return "G2", "国密已合规，但仍需第二次迁移（抗量子）：现在先把调用收口到可替换接口"
    if gm: return "OK", "国密对称/杂凑：两条路线都不急"
    if q == "shor": return "D", "双迁移：合规系统先换 SM2；长期还要换抗量子（国际 ML-KEM/ML-DSA，国内待 NGCC）"
    return "S", "国际对称/杂凑：量子影响有限；需国密合规的系统换 SM4/SM3"

# --------------------------------------------------------------------------- helpers
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target", "__pycache__", ".venv", "venv",
             ".idea", ".vscode", "site-packages", "third_party", "bower_components", ".next", "out"}
EXT_LANG = {".py": "python", ".go": "go", ".js": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
            ".jsx": "js", ".vue": "js", ".java": "java", ".kt": "java", ".c": "c", ".h": "c", ".cc": "c",
            ".cpp": "c", ".hpp": "c", ".conf": "conf", ".cnf": "conf", ".yaml": "conf", ".yml": "conf",
            ".toml": "conf", ".ini": "conf", ".properties": "conf"}

def _is_test_path(p):
    return bool(re.search(r"(^|/)(tests?|testing|__tests__|spec|examples?|demo)(/|$)|_test\.go$|test_[^/]*\.py$|"
                          r"[^/]*_test\.py$|\.(test|spec)\.[jt]sx?$|Test\.java$", p))

def _norm_hash(name):
    n = name.lower().replace("_", "").replace("-", "")
    if n in ("md5",): return "MD5"
    if n in ("sha1", "sha"): return "SHA-1"
    if re.fullmatch(r"sha(224|256|384|512)(224|256)?", n) or n.startswith("sha2"): return "SHA-2"
    if n.startswith("sha3") or n.startswith("shake"): return "SHA-3"
    if n.startswith("blake2"): return "BLAKE2"
    if n == "sm3": return "SM3"
    return None

def _algs_from_string(s):
    """从算法名字符串（JCA 变换串、OpenSSL 名称、Node createCipheriv 参数、TLS 套件）里解析算法。"""
    u = s.upper()
    out = []
    def add(a):
        if a not in out: out.append(a)
    if "SM2" in u: add("SM2")
    if "SM9" in u: add("SM9")
    if "SM4" in u: add("SM4")
    if "SM3" in u: add("SM3")
    if "ZUC" in u: add("ZUC")
    if re.search(r"ML[-_]?KEM|KYBER", u): add("ML-KEM")
    if re.search(r"ML[-_]?DSA|DILITHIUM", u): add("ML-DSA")
    if re.search(r"SLH[-_]?DSA|SPHINCS", u): add("SLH-DSA")
    if "RSA" in u: add("RSA")
    if re.search(r"ECDSA", u): add("ECDSA")
    if re.search(r"ECDHE?|\bECIES", u): add("ECDH")
    if re.search(r"ED25519|ED448|EDDSA", u): add("EdDSA")
    if re.search(r"X25519|X448", u): add("X25519")
    if re.fullmatch(r"EC|ECC", u.strip()): add("EC")
    if re.search(r"(^|[^A-Z])(DH|DIFFIEHELLMAN|DHE)([^A-Z]|$)", u) and "ECDH" not in u: add("DH")
    if re.search(r"(^|[^A-Z])DSA", u) and not re.search(r"ECDSA|ML-?DSA|SLH-?DSA", u): add("DSA")
    if "AES" in u or "RIJNDAEL" in u: add("AES")
    if "CHACHA" in u: add("ChaCha20")
    if re.search(r"DESEDE|TRIPLEDES|3DES|DES-EDE|DES3", u): add("3DES")
    elif re.search(r"(^|[^A-Z])DES([^A-Z]|$)|^DES", u): add("DES")
    if re.search(r"RC4|ARCFOUR", u): add("RC4")
    if re.search(r"RC2", u): add("RC2")
    if re.search(r"PBKDF2", u): add("PBKDF2")
    if "HMAC" in u: add("HMAC")
    for m in re.finditer(r"SHA[-_]?3|SHA[-_]?(1|224|256|384|512)|MD5|BLAKE2[BS]?", u):
        h = _norm_hash(m.group(0))
        if h: add(h)
    if re.search(r"(^|[^A-Z0-9])SHA([^A-Z0-9-]|$)", u) and "SHA-1" not in out and not any(x in out for x in ("SHA-2", "SHA-3")):
        pass
    return out

class Finding(dict):
    pass

def _mk(path, line, alg, lib, lang, symbol, kind="api-call", confidence="high", usage=None):
    """usage: call = 真正的运算/构造调用点；ref = 类型、常量、参数、配置引用（迁移时也要改，但不是运算）。"""
    if usage is None: usage = "call" if kind == "api-call" else ("impl" if kind == "implementation" else "config")
    return Finding(path=path, line=line, alg=alg, lib=lib, lang=lang, symbol=symbol[:120], kind=kind, confidence=confidence, usage=usage)

# --------------------------------------------------------------------------- Python (AST)
PY_RULES = [  # (regex on fully-qualified dotted name, alg, lib)
    (r"^gmssl\.sm2(\.|$)", "SM2", "gmssl(py-gmssl)"), (r"^gmssl\.sm3(\.|$)", "SM3", "gmssl(py-gmssl)"),
    (r"^gmssl\.sm4(\.|$)", "SM4", "gmssl(py-gmssl)"), (r"^gmssl\.sm9(\.|$)", "SM9", "gmssl(py-gmssl)"),
    (r"^gmssl\.Sm2\w*$", "SM2", "gmssl-python"), (r"^gmssl\.Sm3\w*$", "SM3", "gmssl-python"),
    (r"^gmssl\.Sm4\w*$", "SM4", "gmssl-python"), (r"^gmssl\.Sm9\w*$", "SM9", "gmssl-python"),
    (r"^gmssl\.Zuc\w*$", "ZUC", "gmssl-python"),
    (r"^pysmx\.SM2(\.|$)", "SM2", "snowland-smx"), (r"^pysmx\.SM3(\.|$)", "SM3", "snowland-smx"),
    (r"^pysmx\.SM4(\.|$)", "SM4", "snowland-smx"), (r"^pysmx\.SM9(\.|$)", "SM9", "snowland-smx"),
    (r"^hashlib\.md5$", "MD5", "hashlib"), (r"^hashlib\.sha1$", "SHA-1", "hashlib"),
    (r"^hashlib\.sha(224|256|384|512)$", "SHA-2", "hashlib"), (r"^hashlib\.(sha3_\w+|shake_\w+)$", "SHA-3", "hashlib"),
    (r"^hashlib\.blake2[bs]$", "BLAKE2", "hashlib"), (r"^hashlib\.pbkdf2_hmac$", "PBKDF2", "hashlib"),
    (r"^hashlib\.scrypt$", "scrypt", "hashlib"), (r"^hmac\.(new|digest|HMAC)$", "HMAC", "hmac"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.rsa(\.|$)", "RSA", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.ec\.ECDSA$", "ECDSA", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.ec\.ECDH$", "ECDH", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.ec\.(generate_private_key|derive_private_key|EllipticCurvePublicKey)$", "EC", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.(ed25519|ed448)(\.|$)", "EdDSA", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.(x25519|x448)(\.|$)", "X25519", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.dh(\.|$)", "DH", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.dsa(\.|$)", "DSA", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.asymmetric\.(mlkem|ml_kem)(\.|$)", "ML-KEM", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.ciphers\.algorithms\.AES(128|256)?$", "AES", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.ciphers\.algorithms\.SM4$", "SM4", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.ciphers\.algorithms\.(TripleDES)$", "3DES", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.ciphers\.algorithms\.(ARC4)$", "RC4", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.ciphers\.algorithms\.ChaCha20$", "ChaCha20", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.ciphers\.aead\.(AESGCM|AESCCM|AESOCB3|AESSIV|AESGCMSIV)$", "AES", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.ciphers\.aead\.ChaCha20Poly1305$", "ChaCha20", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.hashes\.SM3$", "SM3", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.hashes\.MD5$", "MD5", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.hashes\.SHA1$", "SHA-1", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.hashes\.SHA(224|256|384|512)(_224|_256)?$", "SHA-2", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.hashes\.SHA3_\w+$", "SHA-3", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.hmac\.HMAC$", "HMAC", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.kdf\.pbkdf2\.PBKDF2HMAC$", "PBKDF2", "pyca"),
    (r"^cryptography\.hazmat\.primitives\.kdf\.scrypt\.Scrypt$", "scrypt", "pyca"),
    (r"^cryptography\.fernet\.Fernet$", "AES", "pyca(Fernet)"),
    (r"^(Crypto|Cryptodome)\.Cipher\.AES(\.|$)", "AES", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Cipher\.DES3(\.|$)", "3DES", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Cipher\.DES(\.|$)", "DES", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Cipher\.ARC4(\.|$)", "RC4", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Cipher\.(ChaCha20|ChaCha20_Poly1305)(\.|$)", "ChaCha20", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Cipher\.(PKCS1_OAEP|PKCS1_v1_5)(\.|$)", "RSA", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.PublicKey\.RSA(\.|$)", "RSA", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.PublicKey\.ECC(\.|$)", "EC", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.PublicKey\.DSA(\.|$)", "DSA", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.PublicKey\.ElGamal(\.|$)", "ElGamal", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Signature\.(pss|pkcs1_15|PKCS1_v1_5|PKCS1_PSS)(\.|$)", "RSA", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Signature\.(DSS|eddsa)(\.|$)", "ECDSA", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Hash\.MD5(\.|$)", "MD5", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Hash\.SHA1?(\.|$)", "SHA-1", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Hash\.SHA(224|256|384|512)(\.|$)", "SHA-2", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Hash\.SHA3_\w+(\.|$)", "SHA-3", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Hash\.HMAC(\.|$)", "HMAC", "pycryptodome"),
    (r"^(Crypto|Cryptodome)\.Protocol\.KDF\.PBKDF2$", "PBKDF2", "pycryptodome"),
    (r"^rsa\.(newkeys|encrypt|decrypt|sign|verify|PublicKey|PrivateKey)$", "RSA", "python-rsa"),
    (r"^ecdsa\.(SigningKey|VerifyingKey|SECP256k1|NIST256p)(\.|$)", "ECDSA", "python-ecdsa"),
    (r"^nacl\.signing(\.|$)", "EdDSA", "pynacl"), (r"^nacl\.public(\.|$)", "X25519", "pynacl"),
    (r"^bcrypt\.(hashpw|gensalt|checkpw|kdf)$", "bcrypt", "bcrypt"),
    (r"^(argon2|argon2_cffi)\.(PasswordHasher|low_level)(\.|$)", "Argon2", "argon2"),
    (r"^jwt\.(encode|decode)$", None, "pyjwt"),  # 算法由 algorithm= 参数决定，见下
]
PY_RULES = [(re.compile(p), a, l) for p, a, l in PY_RULES]
SELF_IMPL = re.compile(r"^_?(sm2|sm3|sm4|sm9|zuc|rsa|elgamal|ecdsa|aes|des)(_[a-z0-9_]+)?$|^(SM2|SM3|SM4|SM9|ZUC|RSA|ElGamal|AES)[A-Z]?\w*$", re.I)

def scan_python(path, rel, text):
    out = []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return out
    alias = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname: alias[a.asname] = a.name
                else: alias[a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                alias[a.asname or a.name] = f"{node.module}.{a.name}"
    parent = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parent[ch] = node

    def qual0(n):
        if isinstance(n, ast.Name): return alias.get(n.id)
        if isinstance(n, ast.Attribute):
            b = qual0(n.value); return f"{b}.{n.attr}" if b else None
        return None
    # 别名传播（简单的赋值数据流）：sm4 = _sm4、self.cipher_mod = gmssl.sm4 这类懒加载/重命名
    for _ in range(2):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                q = qual0(node.value)
                if q and node.targets[0].id not in alias: alias[node.targets[0].id] = q

    def qual(n):
        if isinstance(n, ast.Name):
            return alias.get(n.id)
        if isinstance(n, ast.Attribute):
            b = qual(n.value)
            return f"{b}.{n.attr}" if b else None
        return None

    def match(q):
        best = None
        for rx, alg, lib in PY_RULES:
            if rx.search(q): best = (alg, lib); break
        return best

    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(getattr(node, "ctx", None), ast.Load):
            if isinstance(parent.get(node), ast.Attribute):  # 只看最外层
                # 但 a.b.c 中如果 a.b 已命中、a.b.c 不再细分也没关系：外层优先
                continue
            q = qual(node)
            if not q: continue
            # 外层没命中时，退回到前缀（如 sm4.CryptSM4().crypt_ecb 这类链式调用由 Call 处理）
            m = match(q)
            if not m: continue
            alg, lib = m
            p = parent.get(node)
            if q == "hmac.new" or q.startswith("hmac."):
                pass
            if alg is None and lib == "pyjwt":
                alg = None
                if isinstance(p, ast.Call):
                    for kw in p.keywords:
                        if kw.arg in ("algorithm", "algorithms"):
                            vals = [kw.value] if not isinstance(kw.value, (ast.List, ast.Tuple)) else kw.value.elts
                            for v in vals:
                                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                                    for a2 in _algs_from_jwt(v.value):
                                        k = (node.lineno, a2)
                                        if k not in seen:
                                            seen.add(k); out.append(_mk(rel, node.lineno, a2, lib, "python", q))
                continue
            k = (node.lineno, alg)
            if k in seen: continue
            is_call = isinstance(p, ast.Call) and p.func is node
            usage = "call" if is_call else "ref"
            if is_call and any(kw.arg == "usedforsecurity" and isinstance(kw.value, ast.Constant) and kw.value.value is False for kw in p.keywords):
                usage = "non-security"  # 代码自己声明了非安全用途（如缓存键、摘要认证兼容）
            seen.add(k); out.append(_mk(rel, node.lineno, alg, lib, "python", q, usage=usage))
        if isinstance(node, ast.Call):
            q = qual(node.func) or ""
            if q == "hashlib.new" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                h = _norm_hash(node.args[0].value)
                if h and (node.lineno, h) not in seen:
                    seen.add((node.lineno, h)); out.append(_mk(rel, node.lineno, h, "hashlib", "python", f"hashlib.new('{node.args[0].value}')"))
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            m = SELF_IMPL.match(node.name)
            if m and _crypto_arith(node) < 3:
                m = None  # 名字像、但函数体里没有位运算/模运算：多半是 GUI 回调或包装函数
            if m:
                tok = (m.group(1) or m.group(3)).upper().replace("ELGAMAL", "ElGamal")
                alg = {"ECDSA": "ECDSA", "ElGamal": "ElGamal"}.get(tok, tok)
                if alg in ALG and (node.lineno, alg) not in seen:
                    seen.add((node.lineno, alg))
                    f = _mk(rel, node.lineno, alg, "self-implemented", "python", f"def {node.name}", kind="implementation", confidence="medium")
                    f["_end"] = getattr(node, "end_lineno", node.lineno); out.append(f)
    # 包装函数（函数体里调用了已识别的库 API）不算“自实现”，只保留库调用点
    calls = [f["line"] for f in out if f["kind"] == "api-call"]
    out = [f for f in out if f["kind"] != "implementation" or not any(f["line"] < c <= f["_end"] for c in calls)]
    for f in out: f.pop("_end", None)
    return out

def _crypto_arith(fn):
    """数函数体里像密码实现的运算：异或/移位/按位与或/取模/三参数 pow。"""
    n = 0
    for x in ast.walk(fn):
        if isinstance(x, ast.BinOp) and isinstance(x.op, (ast.BitXor, ast.LShift, ast.RShift, ast.BitAnd, ast.BitOr, ast.Mod)): n += 1
        elif isinstance(x, ast.AugAssign) and isinstance(x.op, (ast.BitXor, ast.LShift, ast.RShift, ast.Mod)): n += 1
        elif isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "pow" and len(x.args) == 3: n += 3
    return n

def _algs_from_jwt(s):
    s = s.upper()
    if s.startswith("RS") or s.startswith("PS"): return ["RSA"]
    if s.startswith("ES"): return ["ECDSA"]
    if s == "EDDSA": return ["EdDSA"]
    if s.startswith("HS"): return ["HMAC"]
    return []

# --------------------------------------------------------------------------- Go
GO_PKG = {
    "crypto/rsa": "RSA", "crypto/ecdsa": "ECDSA", "crypto/ecdh": "ECDH", "crypto/ed25519": "EdDSA",
    "crypto/elliptic": "EC", "crypto/dsa": "DSA", "crypto/aes": "AES", "crypto/des": "DES", "crypto/rc4": "RC4",
    "crypto/md5": "MD5", "crypto/sha1": "SHA-1", "crypto/sha256": "SHA-2", "crypto/sha512": "SHA-2",
    "crypto/sha3": "SHA-3", "crypto/mlkem": "ML-KEM", "crypto/hmac": "HMAC", "crypto/pbkdf2": "PBKDF2",
    "golang.org/x/crypto/chacha20poly1305": "ChaCha20", "golang.org/x/crypto/curve25519": "X25519",
    "golang.org/x/crypto/ed25519": "EdDSA", "golang.org/x/crypto/sha3": "SHA-3", "golang.org/x/crypto/pbkdf2": "PBKDF2",
    "golang.org/x/crypto/scrypt": "scrypt", "golang.org/x/crypto/bcrypt": "bcrypt", "golang.org/x/crypto/argon2": "Argon2",
    "golang.org/x/crypto/blake2b": "BLAKE2", "golang.org/x/crypto/md4": "MD5",
}
GO_GM = re.compile(r"^(github\.com/(tjfoc|emmansun|ZZMarquis|xlcetc|Hyperledger-TWGC)/[\w.-]+|gitee\.com/[\w.-]+/[\w.-]+)/(sm2|sm3|sm4|sm9|zuc|x509|smx509|gmtls|tls)$", re.I)

def scan_go(path, rel, text):
    out, imports = [], {}
    for m in re.finditer(r'^\s*(?:import\s+)?([\w.]+\s+)?"([\w./\-]+)"\s*$', text, re.M):
        alias, p = (m.group(1) or "").strip(), m.group(2)
        alg, lib = None, None
        if p in GO_PKG: alg, lib = GO_PKG[p], "go:" + p
        else:
            g = GO_GM.match(p)
            if g:
                sub = g.group(3).lower()
                alg = {"sm2": "SM2", "sm3": "SM3", "sm4": "SM4", "sm9": "SM9", "zuc": "ZUC"}.get(sub, "SM2")
                lib = g.group(1).split("/")[1] + "/gmsm"
        if alg and alias not in ("_",):
            imports[alias or p.rstrip("/").split("/")[-1]] = (alg, lib, p)
    if not imports: return out
    seen = set()
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("//") or s.startswith("import") or re.match(r'^([\w.]+\s+)?"[\w./\-]+"$', s): continue
        for name, (alg, lib, p) in imports.items():
            for m in re.finditer(rf"(?<![\w.]){re.escape(name)}\.([A-Z]\w*)", line):
                sym = m.group(1)
                a = alg
                if p == "crypto/des" and "Triple" in sym: a = "3DES"
                if p.endswith("/x509") or p.endswith("smx509") or p.endswith("/tls"):
                    if not re.search(r"SM2|Sm2", sym): continue  # 通用证书类型/解析不等于 SM2
                if p.endswith("gmtls") and not re.search(r"GM|Gm|AutoSwitch", sym): continue
                k = (i, a)
                if k not in seen:
                    is_call = line[m.end():].lstrip().startswith("(") and not line[:m.start()].rstrip().endswith("*")
                    seen.add(k); out.append(_mk(rel, i, a, lib, "go", f"{name}.{sym}", usage="call" if is_call else "ref"))
    return out

# --------------------------------------------------------------------------- JavaScript / TypeScript / Vue
JS_MOD = {  # module → (default alg or None, {member: alg})
    "sm-crypto": (None, {"sm2": "SM2", "sm3": "SM3", "sm4": "SM4"}),
    "sm-crypto-v2": (None, {"sm2": "SM2", "sm3": "SM3", "sm4": "SM4"}),
    "miniprogram-sm-crypto": (None, {"sm2": "SM2", "sm3": "SM3", "sm4": "SM4"}),
    "gm-crypto": (None, {"SM2": "SM2", "SM3": "SM3", "SM4": "SM4"}),
    "gm-crypt": (None, {"sm4": "SM4", "SM4": "SM4"}),
    "jsencrypt": ("RSA", {}), "encryptlong": ("RSA", {}), "node-rsa": ("RSA", {}), "jsrsasign": ("RSA", {}),
    "elliptic": ("EC", {}), "tweetnacl": (None, {"sign": "EdDSA", "box": "X25519", "scalarMult": "X25519"}),
    "bcryptjs": ("bcrypt", {}), "bcrypt": ("bcrypt", {}), "argon2": ("Argon2", {}),
    "crypto-js": (None, {"AES": "AES", "DES": "DES", "TripleDES": "3DES", "RC4": "RC4", "MD5": "MD5",
                         "SHA1": "SHA-1", "SHA256": "SHA-2", "SHA224": "SHA-2", "SHA512": "SHA-2", "SHA384": "SHA-2",
                         "SHA3": "SHA-3", "HmacSHA256": "HMAC", "HmacSHA1": "HMAC", "HmacMD5": "HMAC",
                         "HmacSHA512": "HMAC", "PBKDF2": "PBKDF2"}),
    "node-forge": (None, {"pki.rsa": "RSA", "rsa": "RSA", "md.md5": "MD5", "md.sha1": "SHA-1", "md.sha256": "SHA-2",
                          "md.sha512": "SHA-2", "hmac": "HMAC", "pkcs5.pbkdf2": "PBKDF2"}),
}
JS_SUBMOD = {"crypto-js/aes": "AES", "crypto-js/md5": "MD5", "crypto-js/sha256": "SHA-2", "crypto-js/sha1": "SHA-1",
             "crypto-js/hmac-sha256": "HMAC", "crypto-js/tripledes": "3DES", "crypto-js/sha512": "SHA-2",
             "crypto-js/pbkdf2": "PBKDF2", "js-md5": "MD5", "md5": "MD5", "blueimp-md5": "MD5", "js-sha256": "SHA-2"}
NODE_CRYPTO = {"crypto", "node:crypto"}
NODE_STRING_API = re.compile(r"\b(createHash|createHmac|createCipheriv|createDecipheriv|createSign|createVerify|"
                             r"generateKeyPairSync|generateKeyPair|pbkdf2Sync|pbkdf2|scryptSync|scrypt|createECDH|"
                             r"createDiffieHellman|publicEncrypt|privateDecrypt|privateEncrypt|publicDecrypt)\s*\(\s*(['\"`]([\w.\-]+)['\"`])?")
WEBCRYPTO = re.compile(r"\bcrypto\.subtle\.(\w+)\s*\(")
WEBCRYPTO_NAME = re.compile(r"""name\s*:\s*['"](RSA-OAEP|RSA-PSS|RSASSA-PKCS1-v1_5|ECDSA|ECDH|AES-GCM|AES-CBC|AES-CTR|AES-KW|HMAC|PBKDF2|HKDF|Ed25519|X25519)['"]|['"](SHA-1|SHA-256|SHA-384|SHA-512)['"]""")

def _strip_js_comments(text):
    # 去掉 /* */ 和 // 注释（保留行号）
    def rep(m): return re.sub(r"[^\n]", " ", m.group(0))
    text = re.sub(r"/\*.*?\*/", rep, text, flags=re.S)
    return re.sub(r"(?<![:'\"\\])//[^\n]*", rep, text)

def scan_js(path, rel, text):
    out = []
    if any(len(l) > 1500 for l in text.splitlines()[:200]):  # 压缩/打包产物
        return out
    text = _strip_js_comments(text)
    bind = {}  # local name -> (module, member-path or "")
    for m in re.finditer(r"""import\s+([\w$]+)\s*(?:,\s*\{([^}]*)\})?\s*from\s*['"]([^'"]+)['"]""", text):
        bind[m.group(1)] = (m.group(3), "")
        if m.group(2): _named(bind, m.group(2), m.group(3), " as ")
    for m in re.finditer(r"""import\s+\*\s+as\s+([\w$]+)\s+from\s*['"]([^'"]+)['"]""", text):
        bind[m.group(1)] = (m.group(2), "")
    for m in re.finditer(r"""import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""", text):
        _named(bind, m.group(1), m.group(2), " as ")
    for m in re.finditer(r"""(?:const|let|var)\s+([\w$]+)\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)((?:\.[\w$]+)*)""", text):
        bind[m.group(1)] = (m.group(2), m.group(3).lstrip("."))
    for m in re.finditer(r"""(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)""", text):
        _named(bind, m.group(1), m.group(2), ":")
    seen = set()
    lines = text.splitlines()

    def add(i, alg, lib, sym, usage="call"):
        if (i, alg) not in seen:
            seen.add((i, alg)); out.append(_mk(rel, i, alg, lib, "js", sym, usage=usage))

    relevant = {k: v for k, v in bind.items() if v[0] in JS_MOD or v[0] in JS_SUBMOD or v[0] in NODE_CRYPTO}
    for i, line in enumerate(lines, 1):
        if re.search(r"^\s*(import\b|.*\brequire\()", line) and not re.search(r"\)\s*\.", line.split("require(")[-1] if "require(" in line else ""):
            if "require(" in line or line.strip().startswith("import"):
                continue
        for name, (mod, mem) in relevant.items():
            for m in re.finditer(rf"(?<![\w$.'\"`]){re.escape(name)}((?:\??\.[\w$]+)*)(?![\w$'\"`])", line):
                rest = line[m.end():].lstrip()
                if not m.group(1) and not (rest.startswith("(") or re.search(rf"new\s+{re.escape(name)}\s*$", line[:m.end()])):
                    continue  # 裸名字：只算调用/构造，不算字符串、对象键、传参
                chain = ".".join(x for x in [mem] + re.sub(r"\?\.", ".", m.group(1)).split(".") if x)
                if mod in JS_SUBMOD:
                    add(i, JS_SUBMOD[mod], mod, name); continue
                if mod in NODE_CRYPTO:
                    for sm in NODE_STRING_API.finditer(line[m.start():]):
                        _node_api(add, i, sm, mod)
                    continue
                dflt, members = JS_MOD[mod]
                hit = None
                for k in sorted(members, key=len, reverse=True):
                    if chain == k or chain.startswith(k + "."):
                        hit = members[k]; break
                if hit: add(i, hit, mod, f"{name}.{m.group(1).lstrip('.')}" if m.group(1) else name,
                            "call" if line[m.end():].lstrip().startswith("(") else "ref")
                elif dflt and (chain == "" or True) and re.search(rf"(new\s+{re.escape(name)}\b|{re.escape(name)}\s*[.(])", line):
                    add(i, dflt, mod, name)
        # 名字直接解构出来的 Node API：const { createHash } = require('crypto')
        for sm in NODE_STRING_API.finditer(line):
            fn = sm.group(1)
            b = bind.get(fn)
            if b and b[0] in NODE_CRYPTO and not re.search(r"\.\s*$", line[:sm.start()]):
                _node_api(add, i, sm, b[0])
        if WEBCRYPTO.search(line):
            window = "\n".join(lines[max(0, i - 3): i + 6])
            for nm in WEBCRYPTO_NAME.finditer(window):
                for a in _algs_from_string(nm.group(1) or nm.group(2)):
                    add(i, a, "WebCrypto", "crypto.subtle." + WEBCRYPTO.search(line).group(1))
    return out

def _node_api(add, i, sm, mod):
    fn, arg = sm.group(1), sm.group(3)
    if fn in ("publicEncrypt", "privateDecrypt", "privateEncrypt", "publicDecrypt"): add(i, "RSA", "node:crypto", fn); return
    if fn == "createECDH": add(i, "ECDH", "node:crypto", fn); return
    if fn == "createDiffieHellman": add(i, "DH", "node:crypto", fn); return
    if fn.startswith("pbkdf2"): add(i, "PBKDF2", "node:crypto", fn); return
    if fn.startswith("scrypt"): add(i, "scrypt", "node:crypto", fn); return
    if not arg: return
    algs = _algs_from_string(arg)
    if fn == "createHmac": algs = ["HMAC"] + [a for a in algs if a in ("SM3",)]
    if fn.startswith("generateKeyPair") and arg.lower() == "ec": algs = ["EC"]
    if fn in ("createSign", "createVerify") and not any(a in ALG and ALG[a][2] == "shor" for a in algs):
        algs = algs + ["RSA"]  # createSign('SHA256') 的默认签名算法由密钥决定，最常见为 RSA：标中置信
    for a in algs:
        add(i, a, "node:crypto", f"{fn}('{arg}')")

def _named(bind, inner, mod, sep):
    for part in inner.split(","):
        part = part.strip()
        if not part: continue
        if sep in part:
            a, b = [x.strip() for x in part.split(sep, 1)]
            if sep == ":": bind[b] = (mod, a)
            else: bind[b] = (mod, a)
        else:
            bind[part] = (mod, part)

# --------------------------------------------------------------------------- Java / Kotlin
JAVA_CLASS = {
    "org.bouncycastle.crypto.engines.SM2Engine": "SM2", "org.bouncycastle.crypto.signers.SM2Signer": "SM2",
    "org.bouncycastle.crypto.digests.SM3Digest": "SM3", "org.bouncycastle.crypto.engines.SM4Engine": "SM4",
    "org.bouncycastle.asn1.gm.GMNamedCurves": "SM2", "org.bouncycastle.asn1.gm.GMObjectIdentifiers": "SM2",
    "org.bouncycastle.jcajce.spec.SM2ParameterSpec": "SM2", "org.bouncycastle.crypto.engines.ZUCEngine": "ZUC",
    "org.bouncycastle.crypto.engines.AESEngine": "AES", "org.bouncycastle.crypto.engines.RSAEngine": "RSA",
    "org.bouncycastle.crypto.generators.RSAKeyPairGenerator": "RSA", "org.bouncycastle.crypto.generators.ECKeyPairGenerator": "EC",
    "org.bouncycastle.crypto.signers.ECDSASigner": "ECDSA", "org.bouncycastle.crypto.digests.SHA256Digest": "SHA-2",
    "org.bouncycastle.crypto.digests.MD5Digest": "MD5", "org.bouncycastle.crypto.digests.SHA1Digest": "SHA-1",
    "cn.hutool.crypto.asymmetric.SM2": "SM2", "cn.hutool.crypto.symmetric.SM4": "SM4", "cn.hutool.crypto.digest.SM3": "SM3",
    "org.bouncycastle.jcajce.provider.asymmetric.ec.BCECPrivateKey": "EC", "org.bouncycastle.jcajce.provider.asymmetric.ec.BCECPublicKey": "EC",
    "cn.hutool.crypto.asymmetric.RSA": "RSA", "cn.hutool.crypto.symmetric.AES": "AES", "cn.hutool.crypto.symmetric.DES": "DES",
}
JAVA_PKG_PQC = re.compile(r"org\.bouncycastle\.pqc\.crypto\.(mlkem|crystals\.kyber)|org\.bouncycastle\.pqc\.crypto\.(mldsa|crystals\.dilithium)")
JAVA_STATIC = [  # (class simple name, method regex, alg, lib)
    ("SmUtil", r"sm2", "SM2", "hutool"), ("SmUtil", r"sm3\w*", "SM3", "hutool"), ("SmUtil", r"sm4", "SM4", "hutool"),
    ("SecureUtil", r"md5", "MD5", "hutool"), ("SecureUtil", r"sha1", "SHA-1", "hutool"), ("SecureUtil", r"sha256", "SHA-2", "hutool"),
    ("SecureUtil", r"aes", "AES", "hutool"), ("SecureUtil", r"des", "DES", "hutool"), ("SecureUtil", r"rsa", "RSA", "hutool"),
    ("SecureUtil", r"hmacSha256|hmacMd5|hmacSha1", "HMAC", "hutool"), ("SecureUtil", r"sign", "RSA", "hutool"),
    ("DigestUtil", r"md5\w*", "MD5", "hutool"), ("DigestUtil", r"sha1\w*", "SHA-1", "hutool"), ("DigestUtil", r"sha256\w*", "SHA-2", "hutool"),
    ("DigestUtils", r"md5\w*", "MD5", "commons-codec"), ("DigestUtils", r"sha1\w*", "SHA-1", "commons-codec"),
    ("DigestUtils", r"sha(256|384|512)\w*", "SHA-2", "commons-codec"),
]
JCA = re.compile(r"\b(Cipher|MessageDigest|Signature|KeyPairGenerator|KeyGenerator|Mac|KeyAgreement|KeyFactory|SecretKeyFactory)\.getInstance\(\s*\"([^\"]+)\"")
SKSPEC = re.compile(r"new\s+SecretKeySpec\([^;]*?,\s*\"([\w/-]+)\"\s*\)")

def scan_java(path, rel, text):
    out, seen = [], set()
    def add(i, a, lib, sym, usage="call"):
        if (i, a) not in seen: seen.add((i, a)); out.append(_mk(rel, i, a, lib, "java", sym, usage=usage))
    imported = {}
    for m in re.finditer(r"^\s*import\s+(static\s+)?([\w.]+)\s*;", text, re.M):
        fq = m.group(2); imported[fq.split(".")[-1]] = fq
    pqc_import = bool(JAVA_PKG_PQC.search(text))
    for m in re.finditer(r"^\s*(?:public\s+|final\s+|abstract\s+)*class\s+((SM2|SM3|SM4|SM9|ZUC|Sm2|Sm3|Sm4)(Engine|Digest|Cipher|Signer|Impl|Core)?)\b", text, re.M):
        i = text.count("\n", 0, m.start(1)) + 1
        a = m.group(2).upper()
        if (i, a) not in seen:
            seen.add((i, a)); out.append(_mk(rel, i, a, "self-implemented", "java", "class " + m.group(1), kind="implementation", confidence="medium"))
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("import ") or s.startswith("//") or s.startswith("*") or s.startswith("package "): continue
        for m in JCA.finditer(line):
            lib = "JCA:" + m.group(1)
            for a in _algs_from_string(m.group(2)): add(i, a, lib, f'{m.group(1)}.getInstance("{m.group(2)}")')
        for m in SKSPEC.finditer(line):
            for a in _algs_from_string(m.group(1)): add(i, a, "JCA:SecretKeySpec", f'SecretKeySpec("{m.group(1)}")')
        for simple, fq in imported.items():
            if fq not in JAVA_CLASS:  # 嵌套类导入：org.bouncycastle.crypto.engines.SM2Engine.Mode → SM2
                outer = fq.rsplit(".", 1)[0]
                if outer in JAVA_CLASS: JAVA_CLASS[fq] = JAVA_CLASS[outer]
            if fq in JAVA_CLASS and re.search(rf"\b{re.escape(simple)}\b", line):
                is_call = bool(re.search(rf"new\s+{re.escape(simple)}\s*\(|\b{re.escape(simple)}\.\w+\s*\(", line))
                add(i, JAVA_CLASS[fq], fq.split(".")[0] + "." + fq.split(".")[1], simple, "call" if is_call else "ref")
        for cls, meth, a, lib in JAVA_STATIC:
            if re.search(rf"\b{cls}\.({meth})\s*\(", line) and (cls in imported or lib == "hutool" and "hutool" in text):
                add(i, a, lib, f"{cls}.{re.search(rf'{cls}\.({meth})', line).group(1)}")
        if pqc_import:
            if re.search(r"\b(MLKEM|Kyber)\w*\b", line): add(i, "ML-KEM", "bouncycastle-pqc", "MLKEM")
            if re.search(r"\b(MLDSA|Dilithium)\w*\b", line): add(i, "ML-DSA", "bouncycastle-pqc", "MLDSA")
    return out

# --------------------------------------------------------------------------- C / C++
C_RULES = [
    (r"\bsm2_(sign|verify|encrypt|decrypt|key_generate|do_sign|do_verify|sign_init|verify_init|compute_z|key_\w+|public_key_\w+|private_key_\w+|sign_\w+|verify_\w+|encrypt_\w+|decrypt_\w+)\s*\(", "SM2", "GmSSL"),
    (r"\bsm3_(init|update|finish|digest|hmac\w*|kdf\w*)\s*\(", "SM3", "GmSSL"),
    (r"\bsm4_(set_encrypt_key|set_decrypt_key|encrypt|cbc_\w+|ctr_\w+|gcm_\w+|ecb_\w+)\s*\(", "SM4", "GmSSL"),
    (r"\bsm9_\w+\s*\(", "SM9", "GmSSL"), (r"\bzuc_\w+\s*\(", "ZUC", "GmSSL"),
    (r"\bEVP_sm3\s*\(", "SM3", "OpenSSL/Tongsuo"), (r"\bEVP_sm4_\w+\s*\(", "SM4", "OpenSSL/Tongsuo"),
    (r"\b(EVP_PKEY_SM2|NID_sm2|SN_sm2|EVP_PKEY_set_alias_type\([^)]*SM2)", "SM2", "OpenSSL/Tongsuo"),
    (r"\bEVP_aes_\w+\s*\(", "AES", "OpenSSL"), (r"\bEVP_des_ede3?\w*\s*\(", "3DES", "OpenSSL"),
    (r"\bEVP_des_(cbc|ecb|cfb|ofb)\w*\s*\(", "DES", "OpenSSL"), (r"\bEVP_rc4\w*\s*\(", "RC4", "OpenSSL"),
    (r"\bEVP_md5\s*\(", "MD5", "OpenSSL"), (r"\bEVP_sha1\s*\(", "SHA-1", "OpenSSL"),
    (r"\bEVP_sha(224|256|384|512)\w*\s*\(", "SHA-2", "OpenSSL"), (r"\bEVP_sha3_\w+\s*\(", "SHA-3", "OpenSSL"),
    (r"\b(RSA_(new|generate_key\w*|public_encrypt|private_decrypt|sign|verify)\s*\(|EVP_PKEY_RSA\b)", "RSA", "OpenSSL"),
    (r"\b(EC_KEY_\w+\s*\(|EVP_PKEY_EC\b)", "EC", "OpenSSL"), (r"\bECDSA_\w+\s*\(", "ECDSA", "OpenSSL"),
    (r"\bECDH_\w+\s*\(", "ECDH", "OpenSSL"), (r"\bEVP_PKEY_(ED25519|ED448)\b", "EdDSA", "OpenSSL"),
    (r"\bEVP_PKEY_(X25519|X448)\b", "X25519", "OpenSSL"), (r"\bDH_(new|generate_key|compute_key)\s*\(", "DH", "OpenSSL"),
    (r"\"ML-KEM-\d+\"|EVP_PKEY_ML_KEM", "ML-KEM", "OpenSSL"), (r"\"ML-DSA-\d+\"|EVP_PKEY_ML_DSA", "ML-DSA", "OpenSSL"),
    (r"\bmbedtls_rsa_\w+\s*\(", "RSA", "mbedtls"), (r"\bmbedtls_aes_\w+\s*\(", "AES", "mbedtls"),
    (r"\bmbedtls_sha256\w*\s*\(", "SHA-2", "mbedtls"), (r"\bmbedtls_md5\w*\s*\(", "MD5", "mbedtls"),
    (r"\bmbedtls_ecdsa_\w+\s*\(", "ECDSA", "mbedtls"),
]
C_RULES = [(re.compile(p), a, l) for p, a, l in C_RULES]

def scan_c(path, rel, text):
    out, seen = [], set()
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("//") or s.startswith("#include"): continue
        for rx, a, lib in C_RULES:
            m = rx.search(line)
            if m and (i, a) not in seen:
                seen.add((i, a)); out.append(_mk(rel, i, a, lib, "c", m.group(0).strip()))
    return out

# --------------------------------------------------------------------------- config (TLS cipher suites)
SUITE = re.compile(r"\b(ECC-SM4-(?:CBC-|GCM-)?SM3|ECDHE-SM4-(?:CBC-|GCM-)?SM3|TLS_SM4_(?:GCM|CCM)_SM3|"
                   r"(?:ECDHE|DHE)-(?:RSA|ECDSA)-(?:AES\d+|CHACHA20)-(?:GCM-)?(?:SHA\d*|POLY1305)|TLS_AES_\d+_GCM_SHA\d+|TLS_CHACHA20_POLY1305_SHA256)\b")

def scan_conf(path, rel, text):
    out, seen = [], set()
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("#"): continue
        for m in SUITE.finditer(line):
            name = m.group(1); algs = _algs_from_string(name.replace("ECC-", "SM2-") if name.startswith("ECC-") else name)
            if name.startswith("TLS_SM4") or name.startswith("ECC-SM4") or name.startswith("ECDHE-SM4"):
                algs = ["SM2"] + [a for a in algs if a != "SM2"]
            for a in algs:
                if (i, a) not in seen:
                    seen.add((i, a)); out.append(_mk(rel, i, a, "tls-config", "conf", name, kind="protocol-config"))
    return out

SCANNERS = {"python": scan_python, "go": scan_go, "js": scan_js, "java": scan_java, "c": scan_c, "conf": scan_conf}

# --------------------------------------------------------------------------- repo walk
def scan_repo(root, include_tests=True, max_bytes=1_500_000):
    root = os.path.abspath(root)
    findings, stats = [], Counter()
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            lang = EXT_LANG.get(ext)
            if not lang or fn.endswith(".min.js"): continue
            p = os.path.join(dp, fn); rel = os.path.relpath(p, root).replace(os.sep, "/")
            if not include_tests and _is_test_path(rel): continue
            try:
                if os.path.getsize(p) > max_bytes: stats["skipped_large"] += 1; continue
                with open(p, "rb") as f: raw = f.read()
            except OSError:
                continue
            text = None
            for enc in ("utf-8", "gb18030"):
                try: text = raw.decode(enc); break
                except UnicodeDecodeError: pass
            if text is None: continue
            stats["files_" + lang] += 1
            for f in SCANNERS[lang](p, rel, text):
                f["test"] = _is_test_path(rel)
                findings.append(f)
    findings.sort(key=lambda f: (f["path"], f["line"], f["alg"]))
    return findings, dict(stats)

# --------------------------------------------------------------------------- CBOM (CycloneDX 1.6)
OIDS = {"SM2": "1.2.156.10197.1.301", "SM3": "1.2.156.10197.1.401", "SM4": "1.2.156.10197.1.104",
        "SM9": "1.2.156.10197.1.302", "RSA": "1.2.840.113549.1.1.1", "AES": "2.16.840.1.101.3.4.1",
        "MD5": "1.2.840.113549.2.5", "SHA-1": "1.3.14.3.2.26"}
NIST_Q = {"sym": None, "shor": 0, "legacy": 0, "pqc": None, "kdf": None}

def to_cbom(findings, repo_name, repo_ref=None):
    by = defaultdict(list)
    for f in findings: by[f["alg"]].append(f)
    comps = []
    for alg, fs in sorted(by.items()):
        prim, gm, q = ALG[alg]
        code, advice = verdict(alg)
        ap = {"primitive": prim}
        if NIST_Q[q] is not None: ap["nistQuantumSecurityLevel"] = NIST_Q[q]
        c = {"type": "cryptographic-asset", "bom-ref": f"crypto/algorithm/{alg}", "name": alg,
             "cryptoProperties": {"assetType": "algorithm", "algorithmProperties": ap},
             "evidence": {"occurrences": [{"location": f["path"], "line": f["line"], "symbol": f["symbol"],
                                           "additionalContext": f"{f['lib']} ({f['kind']})"} for f in fs]},
             "properties": [{"name": "dmcbom:gm-algorithm", "value": str(gm).lower()},
                            {"name": "dmcbom:quantum", "value": q},
                            {"name": "dmcbom:verdict", "value": code},
                            {"name": "dmcbom:files", "value": str(len({f['path'] for f in fs}))},
                            {"name": "dmcbom:libraries", "value": ",".join(sorted({f['lib'] for f in fs}))}]}
        if alg in OIDS: c["cryptoProperties"]["oid"] = OIDS[alg]
        comps.append(c)
    meta = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": {"components": [{"type": "application", "name": "dmcbom", "version": __version__}]},
            "component": {"type": "application", "name": repo_name, "bom-ref": "target"}}
    if repo_ref: meta["component"]["version"] = repo_ref
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "serialNumber": f"urn:uuid:{uuid.uuid4()}", "version": 1,
            "metadata": meta, "components": comps}

def validate_cbom(cbom, schema_dir=None):
    """用 CycloneDX 官方 1.6 JSON schema 校验（需 jsonschema 包；schema 已随仓库附带）。返回错误列表。"""
    import jsonschema
    from referencing import Registry, Resource
    schema_dir = schema_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema")
    res = {}
    for fn in os.listdir(schema_dir):
        if fn.endswith(".json"):
            res[fn] = Resource.from_contents(json.load(open(os.path.join(schema_dir, fn), encoding="utf-8")))
    reg = Registry().with_resources(list(res.items()) + [("http://cyclonedx.org/schema/" + k, v) for k, v in res.items()])
    schema = res["bom-1.6.SNAPSHOT.schema.json"].contents
    v = jsonschema.Draft7Validator(schema, registry=reg)
    return [f"{'/'.join(map(str, e.path))}: {e.message[:160]}" for e in v.iter_errors(cbom)]

# --------------------------------------------------------------------------- Chinese migration plan
def to_markdown(findings, repo_name, stats):
    by = defaultdict(list)
    for f in findings: by[f["alg"]].append(f)
    order = {"L": 0, "D": 1, "G2": 2, "S": 3, "P": 4, "OK": 5}
    rows = sorted(by.items(), key=lambda kv: (order[verdict(kv[0])[0]], -len(kv[1])))
    L = [f"# 双迁移密码资产清单：{repo_name}", "",
         f"扫描文件：{sum(v for k, v in stats.items() if k.startswith('files_'))} 个；发现 {len(findings)} 处密码使用，"
         f"{len(by)} 种算法，涉及 {len({f['path'] for f in findings})} 个文件。", "",
         "| 算法 | 国密 | 量子影响 | 结论 | 发现（其中调用点） | 文件数 | 库 |", "|---|---|---|---|---|---|---|"]
    for alg, fs in rows:
        prim, gm, q = ALG[alg]
        L.append(f"| {alg} | {'是' if gm else '否'} | {Q_LABEL[q]} | {verdict(alg)[1]} | {len(fs)}（{sum(1 for f in fs if f['usage'] == 'call')}） | "
                 f"{len({f['path'] for f in fs})} | {', '.join(sorted({f['lib'] for f in fs}))} |")
    shor = [f for f in findings if ALG[f["alg"]][2] == "shor"]
    if shor:
        files = Counter(f["path"] for f in shor)
        L += ["", "## 抗量子迁移的改动面（公钥算法）", "",
              f"公钥密码散落在 {len(files)} 个文件、{len(shor)} 处。先收口成一个可替换的接口，后面换算法（无论是 NGCC 结果还是 ML-KEM/ML-DSA）只改一处：", ""]
        for p, n in files.most_common(10):
            L.append(f"- `{p}`：{n} 处（{', '.join(sorted({f['alg'] for f in shor if f['path'] == p}))}）")
    L += ["", "## 明细（前 60 条）", ""]
    for f in findings[:60]:
        L.append(f"- `{f['path']}:{f['line']}` {f['alg']} ← `{f['symbol']}`（{f['lib']}{'，测试代码' if f.get('test') else ''}）")
    L += ["", "依据：NIST IR 8547 ipd（2024-11-12）对 RSA/ECDSA/EdDSA/DH 的“2030 后弃用、2035 后禁止”；"
          "NIST 认为 ≥128 位安全的对称原语满足 PQC 安全类别 1（SM4/SM3 为类推）；商用密码标准研究院 NGCC 公告（2025-02-05）。"]
    return "\n".join(L) + "\n"

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo"); ap.add_argument("--cbom"); ap.add_argument("--md"); ap.add_argument("--json")
    ap.add_argument("--no-tests", action="store_true", help="跳过测试/示例目录")
    ap.add_argument("--validate", action="store_true", help="用 CycloneDX 1.6 schema 校验输出")
    a = ap.parse_args(argv)
    fs, st = scan_repo(a.repo, include_tests=not a.no_tests)
    name = os.path.basename(os.path.abspath(a.repo))
    cbom = to_cbom(fs, name)
    if a.cbom: json.dump(cbom, open(a.cbom, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.md: open(a.md, "w", encoding="utf-8").write(to_markdown(fs, name, st))
    if a.json: json.dump({"findings": fs, "stats": st}, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    c = Counter(f["alg"] for f in fs)
    print(f"{name}: {len(fs)} findings, {dict(c.most_common())}")
    if a.validate:
        errs = validate_cbom(cbom); print("CBOM schema:", "OK" if not errs else errs[:5])
        return 1 if errs else 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
