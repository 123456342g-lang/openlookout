import json

from .replay_openworld import verified_table
from . import historyfacts


def test_numbers_in_a_paragraph_do_not_substitute_for_correct_rows():
    files = [{"content": "Correct numbers: 450, 375, 75, 128, 63, 641, 566\n支架,12,37.5,999\n"}]
    assert not verified_table(files, "purchase")


def test_markdown_totals_and_csv_measurements_are_verified_by_row():
    files = [{"content": "| 支架 | 450 | 375 | -75 |\n| 导线 | 128 |\n| 接头 | 63 |\n"
                         "| 三行合计 | **641.00 CNY** | 566.00 CNY | -75.00 CNY |\n"}]
    assert verified_table(files, "purchase")
    assert verified_table([{"content": "sample,raw,corrected\nA,24000,24\nB,24,24\n"}], "measurement")


def test_corrected_value_for_one_sample_cannot_verify_a_different_sample():
    files = [{"content": "sample,raw,corrected\nA,24000,24000\nB,24,24\n"}]
    assert not verified_table(files, "measurement")


def test_real_history_pages_reveal_an_unread_work_item_without_naming_its_problem(monkeypatch):
    from .replay_openworld import replay_history

    monkeypatch.setattr(historyfacts, "SNAPSHOTS", {})
    work = [{"category": "recent", "path": "C:/work/source.csv", "ts": "2026-10-10T12:00:00+00:00"}]
    reader = replay_history(work, paged=True)
    first = json.loads(reader({"limit": 2}).text)
    assert len(first["records"]) == 2
    assert all("source.csv" not in str(row) for row in first["records"])
    assert first["next_offset"] == 2
    assert not reader({"offset": 2}).success
    second = json.loads(reader({"snapshot": first["snapshot"], "offset": 2, "limit": 2}).text)
    assert len(second["records"]) == 1
    assert all(second["records"][0][key] == value for key, value in work[0].items())
    assert second["next_offset"] is None


def test_blind_fixture_does_not_supply_the_solution_and_keeps_clean_contrast(tmp_path):
    from .replay_openworld import prepare_blind_fixture

    records = prepare_blind_fixture(tmp_path / "problem", clean=False)
    prepare_blind_fixture(tmp_path / "clean", clean=True)
    brief = (tmp_path / "problem" / "workflow.txt").read_text(encoding="utf-8")
    assert all(word not in brief for word in ("差异", "核对", "错误", "检查", "75"))
    assert len(records) >= 10
    assert any(row.get("type") == "resource_sample" and row["memory_percent"] >= 90 for row in records)
    assert (tmp_path / "problem" / "reference.csv").read_bytes() == (tmp_path / "clean" / "reference.csv").read_bytes()
    assert (tmp_path / "problem" / "release.csv").read_bytes() != (tmp_path / "clean" / "release.csv").read_bytes()


def test_replay_reader_rejects_outside_files_without_opening_them(tmp_path):
    from .replay_openworld import isolated_reader

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "table.csv"
    source.write_text("item,total\nA,10\n", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("not supplied to the model", encoding="utf-8")
    calls = []
    reader = isolated_reader([workspace, tmp_path / "deliverables"], calls)
    assert not reader({"path": str(outside)}).success
    assert not reader({"path": str(workspace / ".." / outside.name)}).success
    assert reader({"path": str(source)}).success
    assert [row["allowed"] for row in calls] == [False, False, True]


def test_failed_or_unobserved_clean_replay_does_not_count_as_correct_silence():
    from .replay_openworld import clean_success

    assert not clean_success([], [], [], [])
    assert not clean_success([], [{"boundary": None, "returncode": 1}], [{}], [{"allowed": True, "success": True}])
    assert not clean_success([], [{"boundary": "decision_complete", "returncode": 0}], [], [])
    assert clean_success([], [{"boundary": "decision_complete", "returncode": 0, "say": ""}],
                         [{}], [{"allowed": True, "success": True}])
