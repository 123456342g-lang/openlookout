"""python -m unittest test_pubkey_lab -v"""
import random, unittest
from pubkey_lab import *

class T(unittest.TestCase):
    def test_modexp_matches_pow(self):
        r = random.Random(7)
        for _ in range(300):
            b, e, m = r.getrandbits(256), r.getrandbits(256), r.getrandbits(256) | 1
            self.assertEqual(modexp_l2r(b, e, m)[0], pow(b, e, m)); self.assertEqual(modexp_r2l(b, e, m), pow(b, e, m))
    def test_mul_count(self):
        _, sq, mul = modexp_l2r(3, 0b101101, 1000003)
        self.assertEqual((sq, mul), (6, 4))
    def test_primality(self):
        self.assertTrue(is_probable_prime(2**127 - 1))
        for c in (561, 1105, 1729, 2465, 2821, 6601, 2**128 + 1): self.assertFalse(is_probable_prime(c))
    def test_rsa_crt(self):
        k = rsa_keygen(1024)
        for m in (0, 1, 2, 65537, k["n"] - 1):
            c = rsa_enc(k, m); self.assertEqual(rsa_dec(k, c), m); self.assertEqual(rsa_dec_crt(k, c), m)
    def test_interop_with_cryptography(self):
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa, padding
            from cryptography.hazmat.primitives import hashes
        except ImportError:
            self.skipTest("cryptography not installed")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pn = key.private_numbers()
        k = rsa_from_pq(pn.p, pn.q, 65537)
        self.assertEqual(k["d"] % ((pn.p - 1) * (pn.q - 1) // math.gcd(pn.p - 1, pn.q - 1)), pn.d % ((pn.p - 1) * (pn.q - 1) // math.gcd(pn.p - 1, pn.q - 1)))
        self.assertEqual((k["dp"], k["dq"], k["qinv"]), (pn.dmp1, pn.dmq1, pn.iqmp))
        msg = b"lab7 interop"
        sig = key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
        self.assertTrue(pkcs1v15_sha256_verify(k["n"], 65537, msg, sig))
        self.assertFalse(pkcs1v15_sha256_verify(k["n"], 65537, msg + b"!", sig))
    def test_dh_elgamal(self):
        p, q, g = gen_safe_prime_group(128)
        self.assertEqual(pow(g, q, p), 1)
        s1, s2 = dh_demo(p, q, g); self.assertEqual(s1, s2)
        x, y = elgamal_keygen(p, q, g)
        for m in (1, 2, 99999):
            self.assertEqual(elgamal_dec(p, x, *elgamal_enc(p, q, g, y, m)), m)

if __name__ == "__main__":
    unittest.main()
