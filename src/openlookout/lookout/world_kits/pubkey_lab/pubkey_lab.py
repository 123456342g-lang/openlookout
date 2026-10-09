"""公钥密码实验预习包：从"模幂运算/有限域"接到 RSA、DH、ElGamal。
纯 Python、零依赖，教学用（教科书 RSA 没有填充，不能用于真实加密）。
运行：python pubkey_lab.py        # 打印演示和计时
"""
import random, time, math

# ---------- 模幂：两种平方-乘算法（并统计乘法次数，对照上一个实验） ----------
def modexp_l2r(b, e, m):
    """从左到右平方-乘。返回 (结果, 平方次数, 乘法次数)"""
    if m == 1: return 0, 0, 0
    r, sq, mul = 1, 0, 0
    b %= m
    for bit in bin(e)[2:]:
        r = r * r % m; sq += 1
        if bit == "1": r = r * b % m; mul += 1
    return r, sq, mul

def modexp_r2l(b, e, m):
    if m == 1: return 0
    r, b = 1, b % m
    while e:
        if e & 1: r = r * b % m
        b = b * b % m; e >>= 1
    return r

# ---------- 数论工具 ----------
def egcd(a, b):
    x0, x1, y0, y1 = 1, 0, 0, 1
    while b:
        q, a, b = a // b, b, a % b
        x0, x1 = x1, x0 - q * x1; y0, y1 = y1, y0 - q * y1
    return a, x0, y0

def modinv(a, m):
    g, x, _ = egcd(a % m, m)
    if g != 1: raise ValueError("not invertible")
    return x % m

SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p ** .5) + 1, 2))]

def is_probable_prime(n, rounds=40, rng=random.SystemRandom()):
    if n < 2: return False
    for p in [2] + SMALL_PRIMES:
        if n % p == 0: return n == p
    d, s = n - 1, 0
    while d % 2 == 0: d //= 2; s += 1
    for _ in range(rounds):
        a = rng.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1): continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1: break
        else:
            return False
    return True

def gen_prime(bits, rng=random.SystemRandom()):
    while True:
        c = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if is_probable_prime(c): return c

# ---------- RSA（教科书版 + CRT 加速） ----------
def rsa_keygen(bits=2048, e=65537):
    while True:
        p, q = gen_prime(bits // 2), gen_prime(bits // 2)
        if p != q and math.gcd(e, (p - 1) * (q - 1)) == 1: break
    return rsa_from_pq(p, q, e)

def rsa_from_pq(p, q, e=65537):
    n, phi = p * q, (p - 1) * (q - 1)
    d = modinv(e, phi)
    return {"n": n, "e": e, "d": d, "p": p, "q": q, "dp": d % (p - 1), "dq": d % (q - 1), "qinv": modinv(q, p)}

def rsa_enc(k, m): return modexp_r2l(m, k["e"], k["n"])
def rsa_dec(k, c): return modexp_r2l(c, k["d"], k["n"])
def rsa_dec_crt(k, c):
    m1 = modexp_r2l(c, k["dp"], k["p"]); m2 = modexp_r2l(c, k["dq"], k["q"])
    h = k["qinv"] * (m1 - m2) % k["p"]
    return m2 + h * k["q"]

def pkcs1v15_sha256_verify(n, e, msg: bytes, sig: bytes):
    """RSASSA-PKCS1-v1_5 + SHA-256 验签（手写），用于和标准库互验"""
    import hashlib
    k = (n.bit_length() + 7) // 8
    em = modexp_r2l(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    di = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(msg).digest()
    return em == b"\x00\x01" + b"\xff" * (k - 3 - len(di)) + b"\x00" + di

# ---------- DH 与 ElGamal（在素数阶子群上） ----------
def gen_safe_prime_group(bits=256):
    """p = 2q+1，g 生成 q 阶子群。只用于演示（真实场景用 RFC 7919 ffdhe 或 X25519/ML-KEM）"""
    while True:
        q = gen_prime(bits - 1); p = 2 * q + 1
        if is_probable_prime(p): break
    for h in range(2, 100):
        g = pow(h, 2, p)
        if g != 1: return p, q, g

def dh_demo(p, q, g, rng=random.SystemRandom()):
    a, b = rng.randrange(2, q), rng.randrange(2, q)
    A, B = pow(g, a, p), pow(g, b, p)
    return pow(B, a, p), pow(A, b, p)

def elgamal_keygen(p, q, g, rng=random.SystemRandom()):
    x = rng.randrange(2, q); return x, pow(g, x, p)
def elgamal_enc(p, q, g, y, m, rng=random.SystemRandom()):
    k = rng.randrange(2, q); return pow(g, k, p), m * pow(y, k, p) % p
def elgamal_dec(p, x, c1, c2): return c2 * modinv(pow(c1, x, p), p) % p

def bench(bits=2048, n=20):
    k = rsa_keygen(bits); rng = random.SystemRandom()
    cs = [rng.randrange(2, k["n"]) for _ in range(n)]
    t = time.perf_counter(); [rsa_dec(k, c) for c in cs]; plain = (time.perf_counter() - t) / n
    t = time.perf_counter(); [rsa_dec_crt(k, c) for c in cs]; crt = (time.perf_counter() - t) / n
    _, sq, mul = modexp_l2r(cs[0], k["d"], k["n"])
    return {"bits": bits, "dec_ms": plain * 1e3, "dec_crt_ms": crt * 1e3, "speedup": plain / crt,
            "d_bits": k["d"].bit_length(), "squarings": sq, "multiplies": mul}

if __name__ == "__main__":
    k = rsa_keygen(1024); m = 0x6869
    c = rsa_enc(k, m); assert rsa_dec(k, c) == m == rsa_dec_crt(k, c)
    p, q, g = gen_safe_prime_group(256); s1, s2 = dh_demo(p, q, g); assert s1 == s2
    x, y = elgamal_keygen(p, q, g); c1, c2 = elgamal_enc(p, q, g, y, 12345); assert elgamal_dec(p, x, c1, c2) == 12345
    for b in (1024, 2048):
        print(bench(b, 10))
