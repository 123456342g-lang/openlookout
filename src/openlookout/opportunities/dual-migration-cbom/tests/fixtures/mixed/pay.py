import base64
from gmssl import sm2, func
from gmssl.sm4 import CryptSM4, SM4_ENCRYPT
import hashlib as hl
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

# sm2 is mentioned in this comment only; must not count
def sign(priv, pub, data):
    c = sm2.CryptSM2(public_key=pub, private_key=priv)   # SM2 @10
    return c.sign(data, func.random_hex(c.para_len))

def enc(key, data):
    s = CryptSM4()                                       # SM4 @14
    s.set_key(key, SM4_ENCRYPT)                          # SM4 @15
    return s.crypt_ecb(data)

def legacy():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)   # RSA @19
    h = hl.new("md5")                                    # MD5 @20
    return k, h, hashes.SHA256()                         # SHA-2 @21

sm4_key = "not an import"                                # nothing
