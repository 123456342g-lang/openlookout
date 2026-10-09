import hashlib
sm4 = None

def _load():
    global sm4
    from gmssl import sm4 as _sm4
    sm4 = _sm4

def enc(k, b):
    c = sm4.CryptSM4()                       # SM4 @10 via alias propagation
    return c

def cache_key(x):
    return hashlib.md5(x, usedforsecurity=False).hexdigest()   # MD5 @14, non-security

class Gui:
    def _sm3_verify(self):                   # GUI callback, not an implementation
        return self.label.text()

def sm3_rotl(x, n):                          # real implementation fragment @20
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF
