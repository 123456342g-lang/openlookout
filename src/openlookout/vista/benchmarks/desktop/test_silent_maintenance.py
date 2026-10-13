from __future__ import annotations

from vista.benchmarks.desktop.session import DesktopSession
import vista.benchmarks.desktop.session as session_mod


def test_trim_only_is_recorded_but_not_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "CURRENT", tmp_path / "current.json")
    s = DesktopSession("x", {})
    s._turn_mutations.append({"tool": "desktop_trim", "success": True, "text": "已释放闲置工作集"})

    s._companion({"kind": "companion", "say": "我帮你清了 0.3GB 内存", "topic": "内存", "confidence": 0.99})

    assert s.decisions[-1]["kind"] == "quiet"
    assert s.decisions[-1]["say"] == ""
    assert s.action_results == []

