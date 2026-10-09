import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from switch_tax import build_ledger, measure, profile_agent_counts, coverage  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_proj"


class TestSwitchTax(unittest.TestCase):
    def test_ledger_has_kinds(self):
        ledger = build_ledger(FIXTURE)
        self.assertGreaterEqual(ledger["n_facts"], 4)
        kinds = set(ledger["kinds"])
        self.assertTrue({"architecture", "decision"} <= kinds or "architecture" in kinds)
        self.assertIn("constraint", kinds)

    def test_readme_misses_some_decisions(self):
        m = measure(FIXTURE)
        st = m["result"]["switch_tax"]
        # README is short; tax should be > 0
        self.assertGreater(st["tax_facts_n"], 0)
        self.assertLess(st["coverage_readme"], st["coverage_full_ledger"])
        self.assertGreater(st["coverage_full_ledger"], 0.8)

    def test_profile_agent_count(self):
        p = {"tools": ["OpenCode", "Codex CLI", "CC Switch", "Clash Verge", "Ollama"]}
        c = profile_agent_counts(p)
        self.assertEqual(c["coding_agents"], 3)
        self.assertEqual(c["ai_stacks"], 4)  # + Ollama; Clash Verge not matched

    def test_coverage_keyword(self):
        facts = [{"id": "a", "kind": "x", "text": "outbound audit blocks URL", "keys": ["outbound", "audit", "url"]}]
        c = coverage("this pack mentions outbound audit clearly", facts)
        self.assertEqual(c["covered"], 1)


if __name__ == "__main__":
    unittest.main()
