import unittest

from lookout.trajectory import apply_feedback, branch_candidates, correction_assists, render_markdown


class TestTrajectory(unittest.TestCase):
    def test_repeated_corrections_become_one_candidate(self):
        rows = [
            {"ts": "2026-10-01T10:00:00", "instruction": "先跑测试，不要改数据", "scope": "repo-a"},
            {"ts": "2026-10-02T10:00:00", "instruction": "先跑测试，不要改数据。", "scope": "repo-a"},
            {"ts": "2026-10-03T10:00:00", "instruction": "只改代码，先跑测试，不要改数据", "scope": "repo-b"},
        ]
        candidates = correction_assists(rows)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["evidence"]["repetitions"], 2)
        self.assertEqual(candidates[0]["scope"], "repo-a")

    def test_branch_requires_external_match(self):
        finding = {"kind": "tool_stack_churn", "score": 20, "facts": {"distinct_agents": 3}, "local": {}}
        catalog = {"trends": [{
            "id": "new-agent-capability", "date": "2026-10-08", "url": "https://example.com",
            "fact": "新的能力", "opens": "可以做一次隔离实验", "tags": ["ai-agent", "tool-churn"],
            "verified": {"ok": True},
        }]}
        branches = branch_candidates([finding], catalog)
        self.assertEqual(len(branches), 1)
        self.assertIn("新的能力", branches[0]["why_now"])

    def test_branch_aggregates_same_behavior_and_trend(self):
        findings = [
            {"kind": "tool_stack_churn", "score": 20, "facts": {"distinct_agents": 3}, "local": {}},
            {"kind": "tool_stack_churn", "score": 12, "facts": {"distinct_agents": 2}, "local": {}},
        ]
        catalog = {"trends": [{
            "id": "new-agent-capability", "date": "2026-10-08", "url": "https://example.com",
            "fact": "新的能力", "opens": "可以做一次隔离实验", "tags": ["ai-agent", "tool-churn"],
            "verified": {"ok": True},
        }]}
        branches = branch_candidates(findings, catalog)
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["evidence"]["observations"], 2)

    def test_markdown_exposes_evidence_and_test(self):
        text = render_markdown({"generated_at": "now", "assist_candidates": [], "branch_candidates": [{
            "new": True, "title": "分支", "why_now": "证据", "next_test": "小实验",
            "evidence": {"behavior_facts": {"n": 2}, "external": {"url": "https://example.com", "date": "2026-10-08"}},
        }]})
        self.assertIn("证据", text)
        self.assertIn("小实验", text)

    def test_feedback_informs_judgment_without_erasing_candidate(self):
        items = [{"id": "branch-1"}, {"id": "assist-1"}]
        feedback = [{"id": "branch-1", "action": "already_known"}]
        result = apply_feedback(items, feedback)
        self.assertEqual([item["id"] for item in result], ["branch-1", "assist-1"])
        self.assertIn("judgment", result[0])

    def test_conflicting_feedback_requires_context(self):
        item = {"id": "branch-1", "evidence": {"score": 30}}
        feedback = [
            {"id": "branch-1", "action": "useful"},
            {"id": "branch-1", "action": "not_relevant"},
        ]
        result = apply_feedback([item], feedback)[0]
        self.assertEqual(result["judgment"]["state"], "ask")


if __name__ == "__main__":
    unittest.main()
