"""Offline synthetic privacy/context acceptance checks.

This validates the fixture and comparison oracle only; it is not a sanitizer,
transport test, or evidence that production brain/session paths are protected.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parent


def problem_deltas(case: dict, release_key: str) -> list[float] | None:
    if "recipient" in case["source"][0]:
        identities = [row["recipient"] for row in case["source"]]
        if len(set(identities)) != len(identities):
            return None
    expected = {row["item"]: row["quantity"] * row["unit_price"] for row in case["source"] if "item" in row}
    if not expected:
        expected = {row["sample"]: row["length"] * row["width"] * row["height"] / (1000 if row["unit"] == "mm" else 1)
                    for row in case["source"] if "sample" in row}
    if not expected:
        expected = {row["recipient"]: row["quantity"] * row["unit_price"] for row in case["source"]}
    actual = {row.get("item", row.get("sample", row.get("recipient"))): row.get("total", row.get("volume"))
              for row in case[release_key]}
    return [value - actual[key] for key, value in expected.items()]


def views(case: dict) -> dict[str, dict]:
    raw = {key: case[key] for key in ("source", "release_problem", "release_clean", "dependency", "pii_relation", "synthetic_credentials") if key in case}
    credentials_only = dict(raw)
    credentials_only["synthetic_credentials"] = ["[CREDENTIAL REMOVED]"] * len(case["synthetic_credentials"])
    coarse = dict(credentials_only)
    if "recipient" in coarse["source"][0]:
        for collection in ("source", "release_problem", "release_clean"):
            coarse[collection] = [dict(row, recipient="[PERSON]") for row in coarse[collection]]
    if "pii_relation" in coarse:
        coarse["pii_relation"] = "[PERSON]负责报价，[PERSON]负责导出。"
    return {"rich": raw, "credentials_only": credentials_only, "coarse": coarse}


def main() -> None:
    payload = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    assert payload["disclaimer"].startswith("Synthetic only")
    checked = []
    for case in payload["cases"]:
        problem = problem_deltas(case, "release_problem")
        clean = problem_deltas(case, "release_clean")
        assert problem == case["oracle"]["problem_deltas"], (case["id"], problem)
        assert clean == case["oracle"]["clean_deltas"], (case["id"], clean)
        for view in views(case).values():
            assert view["dependency"] == case["dependency"]
        rich, protected, coarse = (views(case)[name] for name in ("rich", "credentials_only", "coarse"))
        assert rich["source"] == protected["source"] == case["source"]
        assert problem_deltas(protected, "release_problem") == problem
        assert problem_deltas(protected, "release_clean") == clean
        protected_text = json.dumps(protected, ensure_ascii=False)
        assert all(secret not in protected_text for secret in case["synthetic_credentials"])
        if case["id"] == "identity_join":
            assert problem_deltas(coarse, "release_problem") is None
        if "problem_ratio" in case["oracle"]:
            assert case["release_problem"][0]["volume"] / case["release_clean"][0]["volume"] == case["oracle"]["problem_ratio"]
        checked.append(case["id"])
    ledger = [{"case_id": case["id"], "view": name, "fields": sorted(view),
               "encoded_bytes": len(json.dumps(view, ensure_ascii=False).encode("utf-8")),
               "destination": "offline_only", "credential_detection": "annotation_only",
               "image_protection": "unknown", "production_coverage": "uncovered"}
              for case in payload["cases"] for name, view in views(case).items()]
    assert all("source" not in row and "dependency" not in row and "text" not in row for row in ledger)
    print(json.dumps({"passed": True, "cases": checked, "ledger": ledger, "transport_requests": 0,
                      "production_protection_claim": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
