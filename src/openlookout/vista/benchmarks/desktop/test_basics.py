"""Tests for the keyless, read-only everyday services."""
from __future__ import annotations

import json
from pathlib import Path

from vista.benchmarks.desktop import actions
from vista.benchmarks.desktop.session import DesktopSession


def payload(reply):
    return json.loads(reply.text)


def test_basic_time_returns_date_and_requested_timezone():
    result = payload(actions.basic_time({"timezone": "Asia/Shanghai"}))
    assert result["ok"] is True
    assert result["timezone"] == "Asia/Shanghai"
    assert result["date"] and result["time"]


def test_basic_time_rejects_unknown_timezone():
    reply = actions.basic_time({"timezone": "Not/AZone"})
    assert reply.success is False
    assert payload(reply)["ok"] is False


def test_basic_calculate_supports_arithmetic():
    result = payload(actions.basic_calculate({"expression": "2 + 3 * 4"}))
    assert result == {"ok": True, "expression": "2 + 3 * 4", "value": 14}


def test_basic_calculate_rejects_code_and_attribute_access():
    for expression in ("__import__('os').getcwd()", "(1).__class__", "open('x')"):
        reply = actions.basic_calculate({"expression": expression})
        assert reply.success is False, expression
        assert payload(reply)["ok"] is False


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body.encode("utf-8")


def test_basic_weather_geocodes_and_fetches_forecast(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout=0):
        calls.append((url, timeout))
        if "geocoding-api" in url:
            return _Response(json.dumps({"results": [{
                "latitude": 31.23, "longitude": 121.47,
                "name": "上海", "admin1": "上海", "country": "中国",
                "timezone": "Asia/Shanghai",
            }]}))
        return _Response(json.dumps({
            "timezone": "Asia/Shanghai",
            "current": {"temperature_2m": 22},
            "daily": {"temperature_2m_max": [25], "temperature_2m_min": [18]},
        }))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = payload(actions.basic_weather({"location": "上海"}))
    assert result["ok"] is True
    assert result["source"] == "Open-Meteo"
    assert result["current"]["temperature_2m"] == 22
    assert result["today"]["temperature_2m_max"] == 25
    assert len(calls) == 2


def test_basic_weather_reports_api_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    reply = actions.basic_weather({"location": "上海"})
    assert reply.success is False
    assert payload(reply)["ok"] is False


def test_basic_search_finds_names_and_text_without_mutating(tmp_path: Path):
    (tmp_path / "notes.md").write_text("the current blocker is API reconnect\n", encoding="utf-8")
    (tmp_path / "worker.py").write_text("print('ok')\n", encoding="utf-8")
    result = payload(actions.basic_search({"root": str(tmp_path), "query": "reconnect", "mode": "text"}))
    assert result["ok"] is True
    assert result["matches"][0]["path"] == "notes.md"
    assert result["matches"][0]["line"] == 1
    assert (tmp_path / "notes.md").read_text(encoding="utf-8").startswith("the current")


def test_basic_search_rejects_invalid_mode(tmp_path: Path):
    reply = actions.basic_search({"root": str(tmp_path), "query": "x", "mode": "delete"})
    assert reply.success is False
    assert payload(reply)["ok"] is False


def test_read_only_basics_do_not_consume_action_budget():
    session = DesktopSession.__new__(DesktopSession)
    session.actions = 0
    session.action_results = []
    session._turn_mutations = []
    for name, arguments in (
        ("basic_time", {}),
        ("basic_calculate", {"expression": "1 + 1"}),
        ("basic_search", {"root": ".", "query": "actions.py", "mode": "name"}),
    ):
        reply = session._handler(name, getattr(actions, name))(arguments)
        assert reply.success is True
    assert session.actions == 0
    assert session.action_results == []


def evidence_visual(screen):
    import io
    from vista.core.contracts import Visual

    height = int(screen.height * 1280 / screen.width)
    buffer = io.BytesIO()
    screen.resize((1280, height)).save(buffer, format="PNG")
    return Visual("screen", "test-current", buffer.getvalue(), 1280, height)


def test_capture_evidence_saves_only_the_purpose_bound_region(monkeypatch, tmp_path):
    from PIL import Image

    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "homework_evidence")
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    monkeypatch.setattr(actions, "_foreground_evidence", lambda: {"process": "browser.exe", "title": "实验结果"})
    screen = Image.new("RGB", (2560, 1600), "white")
    screen.paste("red", (200, 160, 1480, 960))
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: screen)
    reply = actions.capture_evidence({
        "label": "实验结果",
        "purpose": "证明第二步实验输出已经生成",
        "source_id": "test-current",
        "region": {"x": 100, "y": 80, "width": 640, "height": 400},
    }, visual=evidence_visual(screen))
    assert reply.success
    data = json.loads(reply.text)
    image = Path(data["image"])
    metadata = Path(data["metadata"])
    assert image.is_file() and metadata.is_file()
    with Image.open(image) as saved:
        assert saved.size == (1280, 800)
        assert saved.getpixel((640, 400)) == (255, 0, 0)
    assert reply.observation.images()[0]["mime_type"] == "image/png"
    assert data["status"] == "unreviewed"
    record = json.loads((tmp_path / "undo.jsonl").read_text(encoding="utf-8"))
    assert record["undo_kind"] == "homework_evidence"
    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "homework_evidence")
    assert actions.undo({}).success
    assert not image.exists() and not metadata.exists()


def test_capture_evidence_requires_a_real_requirement(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "homework_evidence")
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    missing_purpose = actions.capture_evidence({
        "label": "结果",
        "region": {"x": 10, "y": 10, "width": 300, "height": 200},
    })
    assert missing_purpose.success is False and "证明" in missing_purpose.text


def test_capture_maps_a_16_by_9_screen_without_vertical_distortion(tmp_path, monkeypatch):
    from PIL import Image

    screen = Image.new("RGB", (1920, 1080), "white")
    screen.paste("blue", (150, 300, 750, 600))
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: screen)
    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    reply = actions.capture_evidence({"label": "结果表", "purpose": "证明步骤一的结果与单位",
        "source_id": "test-current", "region": {"x": 100, "y": 200, "width": 400, "height": 200}},
        visual=evidence_visual(screen))
    assert reply.success
    data = payload(reply)
    assert data["pixel_box"] == {"left": 150, "top": 300, "right": 750, "bottom": 600}
    with Image.open(data["image"]) as image:
        assert image.size == (600, 300)
        assert image.getpixel((300, 150)) == (0, 0, 255)


def test_large_evidence_is_not_cropped_by_an_arbitrary_area_limit(tmp_path, monkeypatch):
    from PIL import Image

    screen = Image.new("RGB", (1920, 1080), "white")
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: screen)
    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    reply = actions.capture_evidence({"label": "完整参数和结果", "purpose": "要求三：全部参数及结果必须同时可见",
        "source_id": "test-current", "region": {"x": 0, "y": 0, "width": 1280, "height": 720}},
        visual=evidence_visual(screen))
    assert reply.success
    with Image.open(payload(reply)["image"]) as image:
        assert image.size == (1920, 1080)


def test_capture_refuses_a_changed_result_or_old_source(tmp_path, monkeypatch):
    from PIL import Image

    screen = Image.new("RGB", (1920, 1080), "white")
    visual = evidence_visual(screen)
    screen.paste("black", (150, 300, 750, 600))
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: screen)
    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "evidence")
    args = {"label": "结果表", "purpose": "证明步骤一的结果", "source_id": "test-current",
            "region": {"x": 100, "y": 200, "width": 400, "height": 200}}
    assert "已变化" in actions.capture_evidence(args, visual=visual).text
    assert "过期" in actions.capture_evidence(dict(args, source_id="old"), visual=visual).text
    assert not actions.EVIDENCE_DIR.exists()


def test_capture_journals_before_writing_and_review_rejects_missing_content(tmp_path, monkeypatch):
    from PIL import Image

    screen = Image.new("RGB", (1920, 1080), "white")
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: screen)
    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    original_journal = actions._journal

    def record_before_write(row):
        assert not Path(row["path"]).exists()
        assert not Path(row["metadata"]).exists()
        original_journal(row)

    monkeypatch.setattr(actions, "_journal", record_before_write)
    reply = actions.capture_evidence({"label": "结果表", "purpose": "证明步骤一的结果与单位",
        "source_id": "test-current", "region": {"x": 100, "y": 200, "width": 400, "height": 200}},
        visual=evidence_visual(screen))
    data = payload(reply)
    review = actions.review_evidence({"id": data["id"], "checks": {
        "relevant": True, "complete": False, "legible": True, "focused": True},
        "reason": "图中缺少结果单位，不能证明要求的数值含义"})
    assert payload(review)["status"] == "rejected"
    assert Path(data["image"]).exists()
    assert json.loads(Path(data["metadata"]).read_text(encoding="utf-8"))["status"] == "rejected"
    Path(data["image"]).write_bytes(b"changed")
    assert not actions.review_evidence({"id": data["id"], "checks": {
        "relevant": True, "complete": True, "legible": True, "focused": True}, "reason": "已补齐单位"}).success
    assert not actions.undo({}).success
    assert Path(data["image"]).read_bytes() == b"changed"
    assert Path(data["metadata"]).exists()


def test_evidence_capture_does_not_exhaust_the_desktop_mutation_budget(tmp_path, monkeypatch):
    from PIL import Image

    screen = Image.new("RGB", (320, 200), "white")
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: screen)
    monkeypatch.setattr(actions, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    visual = evidence_visual(screen)
    session = DesktopSession("多步骤实验取证", {}, visual=visual)
    capture = session._handler("desktop_capture_evidence", actions.capture_evidence)
    for index in range(actions.MAX_ACTIONS + 1):
        assert capture({"label": f"步骤{index}", "purpose": f"证明条目{index}的输出",
                        "source_id": visual.source_id,
                        "region": {"x": 100, "y": 100, "width": 500, "height": 300}}).success
    assert session.actions == 0
    assert len(session.action_results) == actions.MAX_ACTIONS + 1

