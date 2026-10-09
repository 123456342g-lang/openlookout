"""惊喜门控单元测试（无网络、无私有数据）。"""
from lookout.surprise import score_finding, gate, MIN_SURPRISE


def _f(kind, facts, fid="X1", **local):
    return {"id": fid, "kind": kind, "score": 20, "facts": facts, "local": local or {}}


def _r(status="verified", arts=("/tmp/a.csv",), **verify):
    return {"status": status, "artifacts": list(arts), "verify_deid": verify, "slots": {}}


def test_reject_site_rhythm_reminder():
    a = score_finding(_f("site_rhythm", {"weeks": 8, "visit_days": 8, "form_submits": 3}),
                      _r("reminder_only", arts=("/tmp/x.ics",)))
    assert not a["passed"]
    assert any("硬拒绝" in r for r in a["reject_reasons"])


def test_reject_recurring_files_expected_chore():
    # 有成品但无潜在不一致 → 拒绝
    a = score_finding(_f("recurring_files", {"occurrences": 12, "period_days": 7, "next_due_in_days": 2},
                         made_by="自己做的"),
                      _r("verified"))
    assert not a["passed"]


def test_pass_version_sprawl_stale_final():
    a = score_finding(_f("version_sprawl", {"versions": 5, "folders": 2, "named_final": 2,
                                           "final_is_not_newest": True, "max_versions_in_48h": 3,
                                           "late_night_saves": 2}),
                      _r("verified"))
    assert a["passed"], a
    assert a["surprise"] >= MIN_SURPRISE
    assert a["metric"] is not None


def test_pass_manual_summary_mismatch():
    a = score_finding(_f("manual_summary", {"workbooks": 2, "detail_sheets": 16, "cells_differ": 34,
                                            "rows_differ": 19, "rows_unexplained": 8, "cells_unexplained": 11,
                                            "rows_explained_by_rule": 11, "rule_found": True,
                                            "identical_copies": 2, "people_rows": 40, "value_columns": 4}),
                      _r("verified"))
    assert a["passed"], a


def test_pass_numbered_series_process_tax():
    a = score_finding(_f("numbered_series", {"episodes": 6, "span_days": 20, "days_per_episode": 3.3,
                                             "deliverable_files": 10, "episodes_with_multiple_files": 3,
                                             "max_files_one_episode": 3, "identical_size_pairs": 1,
                                             "naming_styles": 5, "next_in_days": 4, "weekday_share": 0.7}),
                      _r("verified"))
    assert a["passed"], a


def test_reject_numbered_series_clean():
    # 一期一份、一种命名 → 无流程税
    a = score_finding(_f("numbered_series", {"episodes": 6, "span_days": 20, "days_per_episode": 3.3,
                                             "deliverable_files": 6, "episodes_with_multiple_files": 0,
                                             "max_files_one_episode": 1, "identical_size_pairs": 0,
                                             "naming_styles": 1, "next_in_days": 4, "weekday_share": 0.7}),
                      _r("verified"))
    assert not a["passed"]


def test_gate_max_three():
    findings, results = [], {}
    for i in range(5):
        fid = f"V{i}"
        findings.append(_f("manual_summary", {"workbooks": 1, "detail_sheets": 8, "cells_differ": 10 + i,
                                              "rows_differ": 5, "rows_unexplained": 2, "cells_unexplained": 3,
                                              "rows_explained_by_rule": 3, "rule_found": True,
                                              "identical_copies": 1, "people_rows": 20, "value_columns": 3},
                           fid=fid))
        results[fid] = _r()
    g = gate(findings, results, max_cards=3)
    assert len(g["selected_ids"]) == 3
    assert len(g["overflow_ids"]) == 2


def test_feedback_demotes_attendance():
    from lookout.feedback import multiplier
    from lookout.surprise import gate
    f = {"id": "A", "kind": "manual_summary", "score": 40,
         "facts": {"workbooks": 2, "detail_sheets": 8, "cells_differ": 10, "rows_differ": 5,
                   "rows_unexplained": 2, "cells_unexplained": 3, "rows_explained_by_rule": 3,
                   "rule_found": True, "identical_copies": 1, "people_rows": 20, "value_columns": 3},
         "local": {"parts": [{"file": "考勤表.xlsx"}]}}
    g = {"id": "B", "kind": "numbered_series", "score": 40,
         "facts": {"episodes": 6, "span_days": 20, "days_per_episode": 3, "deliverable_files": 10,
                   "episodes_with_multiple_files": 3, "max_files_one_episode": 3, "identical_size_pairs": 1,
                   "naming_styles": 5, "next_in_days": 4, "weekday_share": 0.7},
         "local": {"prefix": "实验", "root": "课/应用密码学"}}
    res = {"status": "verified", "artifacts": ["/t"], "verify_deid": {},
           "trends": [{"id": "x", "date": "2026-10-06", "url": "https://example.com", "fact": "f", "opens": "o"}]}
    out = gate([f, g], {"A": res, "B": res}, feedback_fn=multiplier)
    assert "A" not in out["selected_ids"]
    assert "B" in out["selected_ids"]


def test_trend_match_crypto():
    from lookout.trends import match_trends, load_catalog
    f = {"kind": "numbered_series", "facts": {}, "local": {"root": "应用密码学/实验"}}
    tr = match_trends(f, load_catalog())
    assert any("pqc" in (t.get("tags") or []) or "openssh" in t["id"] for t in tr)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("all passed")
