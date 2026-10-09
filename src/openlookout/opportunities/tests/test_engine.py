import json, os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from lookout import opportunity_engine as oe

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIG = json.load(open(os.path.join(HERE, "signals", "2026-10-09.json"), encoding="utf-8"))["signals"]
PROF = json.load(open(os.path.join(HERE, "example_profile.json"), encoding="utf-8"))

class TestEngine(unittest.TestCase):
    def test_signals_have_sources(self):
        for s in SIG:
            self.assertTrue(s["url"].startswith("https://"), s["id"])
            self.assertRegex(s["date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(s["fact"] and s["tags"])

    def test_sanitize_drops_excluded(self):
        out, dropped = oe.sanitize(PROF)
        self.assertEqual(dropped, 1)
        self.assertNotIn("CTF", json.dumps(out["topics"], ensure_ascii=False))

    def test_outbound_audit(self):
        self.assertEqual(oe.audit_outbound({"a": "密码学"}), [])
        self.assertIn("url", oe.audit_outbound({"a": "see https://x.y"}))
        self.assertIn("path", oe.audit_outbound({"a": r"C:\Users\me\file"}))

    def test_cross_match_finds_multi_family_themes(self):
        out, _ = oe.sanitize(PROF)
        themes, at = oe.cross_match(out, SIG)
        fams = [set(t["families"]) for t in themes]
        self.assertIn({"compiler", "crypto"}, fams)
        self.assertTrue(any({"gamedev", "local-ai"} <= f for f in fams))
        for t in themes:  # 每个主题至少一条信号单独奖励全部资产
            self.assertTrue(t["signals"])
            self.assertGreaterEqual(len(set(t["families"])), 2)

    def test_validate_rejects_fabrication(self):
        out, _ = oe.sanitize(PROF)
        _, at = oe.cross_match(out, SIG)
        good = {"title": "t", "insight": "i", "why_you": {"assets": ["crypto", "compiler"], "text": ""},
                "why_now": {"signals": ["nist-ir8547"], "text": "2030 年后弃用"},
                "existing_and_gap": {"signals": ["cbomkit-coverage"], "text": ""},
                "first_step": {"build": "x", "success_metric": "在 20 个仓库上复现"}}
        fake_id = json.loads(json.dumps(good)); fake_id["why_now"]["signals"] = ["made-up"]
        fake_num = json.loads(json.dumps(good)); fake_num["why_now"]["text"] = "市场规模 4,500 亿"
        excl = json.loads(json.dumps(good)); excl["insight"] = "打 CTF"
        kept, rej = oe.validate([good, fake_id, fake_num, excl], out, SIG, at)
        self.assertEqual([k["title"] for k in kept], ["t"])
        self.assertEqual(len(rej), 3)

    def test_parse_lenient_extra_brace(self):
        self.assertEqual(oe.parse_lenient('{"opportunities":[{"a":1}}]}')["opportunities"], [{"a": 1}])

if __name__ == "__main__":
    unittest.main()
