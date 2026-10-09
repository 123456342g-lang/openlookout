import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dmcbom

FIX = os.path.join(HERE, "fixtures")

class TestScanner(unittest.TestCase):
    def setUp(self):
        self.fs, self.st = dmcbom.scan_repo(os.path.join(FIX, "mixed"))

    def test_exact_findings_on_mixed_fixture(self):
        got = {(f["path"], f["line"], f["alg"]) for f in self.fs}
        exp = {tuple(x) for x in json.load(open(os.path.join(FIX, "expected_mixed.json")))}
        self.assertEqual(sorted(exp - got), [], "missed")
        self.assertEqual(sorted(got - exp), [], "false positives")

    def test_comments_and_lookalike_names_ignored(self):
        lines = {(f["path"], f["line"]) for f in self.fs}
        for p, l in [("pay.py", 8), ("pay.py", 23), ("main.go", 10), ("login.js", 5), ("login.js", 12), ("Gm.java", 8), ("gm.c", 2), ("nginx.conf", 1)]:
            self.assertNotIn((p, l), lines)

    def test_two_axes(self):
        self.assertEqual(dmcbom.verdict("SM2")[0], "G2")   # 国密但 Shor 可破 → 第二次迁移
        self.assertEqual(dmcbom.verdict("RSA")[0], "D")    # 双迁移
        self.assertEqual(dmcbom.verdict("SM4")[0], "OK")
        self.assertEqual(dmcbom.verdict("AES")[0], "S")
        self.assertEqual(dmcbom.verdict("MD5")[0], "L")
        self.assertEqual(dmcbom.verdict("ML-KEM")[0], "P")

    def test_string_parsing(self):
        self.assertEqual(dmcbom._algs_from_string("SM3withSM2"), ["SM2", "SM3"])
        self.assertEqual(dmcbom._algs_from_string("SHA256withRSA"), ["RSA", "SHA-2"])
        self.assertEqual(dmcbom._algs_from_string("DESede/CBC/PKCS5Padding"), ["3DES"])
        self.assertEqual(dmcbom._algs_from_string("sm4-cbc"), ["SM4"])
        self.assertEqual(dmcbom._algs_from_string("ML-KEM-768"), ["ML-KEM"])

    def test_cbom_validates_against_official_schema(self):
        cbom = dmcbom.to_cbom(self.fs, "mixed")
        self.assertEqual(dmcbom.validate_cbom(cbom), [])
        names = {c["name"] for c in cbom["components"]}
        self.assertTrue({"SM2", "SM3", "SM4", "RSA", "MD5"} <= names)
        sm2 = next(c for c in cbom["components"] if c["name"] == "SM2")
        props = {p["name"]: p["value"] for p in sm2["properties"]}
        self.assertEqual(props["dmcbom:gm-algorithm"], "true")
        self.assertEqual(props["dmcbom:quantum"], "shor")
        self.assertEqual(sm2["cryptoProperties"]["algorithmProperties"]["nistQuantumSecurityLevel"], 0)

    def test_markdown(self):
        md = dmcbom.to_markdown(self.fs, "mixed", self.st)
        self.assertIn("国密已合规，但仍需第二次迁移", md)
        self.assertIn("抗量子迁移的改动面", md)

    def test_minified_js_skipped(self):
        import tempfile
        d = tempfile.mkdtemp()
        open(os.path.join(d, "bundle.js"), "w").write("const {sm2}=require('sm-crypto');" + "x;" * 2000 + "sm2.doEncrypt(a,b)\n")
        self.assertEqual(dmcbom.scan_repo(d)[0], [])

class TestPythonEdges(unittest.TestCase):
    def test_alias_usage_and_selfimpl(self):
        fs, _ = dmcbom.scan_repo(os.path.join(FIX, "py_edge"))
        got = {(f["line"], f["alg"], f["usage"]) for f in fs}
        self.assertIn((10, "SM4", "call"), got)
        self.assertIn((14, "MD5", "non-security"), got)
        self.assertIn((20, "SM3", "impl"), got)
        self.assertFalse(any(f["line"] == 17 for f in fs), "GUI method named _sm3_verify is not crypto")

if __name__ == "__main__":
    unittest.main()
