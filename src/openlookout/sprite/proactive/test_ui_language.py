"""UI language: Windows display language, OPENLOOKOUT_LANG, and English fallback."""
from __future__ import annotations

import pytest

from sprite import i18n
from sprite.i18n import language_directive, t, ui_language, windows_ui_language
from vista.benchmarks.desktop.profiles import SYSTEM, make_profile


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("zh", "zh"),
        ("ZH", "zh"),
        ("zh-CN", "zh"),
        ("zh_TW", "zh"),
        ("zh-Hans", "zh"),
        ("en", "en"),
        ("en-US", "en"),
        ("fr", "en"),
        ("ja-JP", "en"),
        ("chinese", "en"),
    ],
)
def test_override_maps_zh_star_to_chinese_and_everything_else_to_english(raw, expected):
    assert ui_language(environ={"OPENLOOKOUT_LANG": raw}) == expected


def test_override_beats_windows_locale_and_langid():
    env = {"OPENLOOKOUT_LANG": "en"}
    assert ui_language(env, locale_name="zh-CN", langid=0x0804) == "en"


def test_blank_override_falls_through_to_locale():
    assert ui_language(environ={"OPENLOOKOUT_LANG": "  ", "LANG": "zh_CN.UTF-8"}) == "zh"
    assert ui_language(environ={"OPENLOOKOUT_LANG": "", "LC_ALL": "en_GB.UTF-8"}) == "en"


def test_posix_locale_order_and_empty_fallback():
    assert ui_language(environ={"LC_ALL": "zh_TW.UTF-8", "LANG": "en_US.UTF-8"}) == "zh"
    assert ui_language(environ={"LC_ALL": "C", "LC_MESSAGES": "zh_HK.UTF-8"}) == "zh"
    assert ui_language(environ={"LC_ALL": "POSIX", "LANG": "C"}, process_locale="") == "en"
    assert ui_language(environ={"LC_ALL": "C"}, process_locale="zh_CN") == "zh"
    assert ui_language(environ={"LANG": "fr_FR.UTF-8"}, process_locale="zh_CN") == "en"


def test_windows_ui_language_prefers_locale_name_then_langid():
    assert windows_ui_language(langid=0x0804, locale_name="zh-CN") == "zh"
    assert windows_ui_language(langid=0x0404, locale_name="zh-TW") == "zh"
    assert windows_ui_language(langid=0x0C04, locale_name="") == "zh"
    assert windows_ui_language(langid=0x0409, locale_name="en-US") == "en"
    assert windows_ui_language(langid=0x0804, locale_name="en-US") == "en"
    assert windows_ui_language(langid=0x0409, locale_name="") == "en"
    assert windows_ui_language(langid=None, locale_name="") == "en"
    assert ui_language(environ={}, locale_name="zh-HK") == "zh"
    assert ui_language(environ={}, langid=0x0804) == "zh"
    assert ui_language(environ={}, langid=0x0409) == "en"


def test_missing_catalog_key_falls_back_to_english_then_the_key(monkeypatch):
    monkeypatch.setenv("OPENLOOKOUT_LANG", "zh")
    chinese = dict(i18n.STRINGS["zh"])
    chinese.pop("undo")
    monkeypatch.setitem(i18n.STRINGS, "zh", chinese)
    assert t("undo") == "Undo"
    assert t("not-a-real-key") == "not-a-real-key"


def test_catalog_switches_with_the_override(monkeypatch):
    monkeypatch.setenv("OPENLOOKOUT_LANG", "zh-CN")
    assert t("accept") == "好的"
    assert t("decline") == "不用"
    assert t("undo") == "撤销"
    assert "只用中文" in language_directive()
    monkeypatch.setenv("OPENLOOKOUT_LANG", "fr")
    assert t("accept") == "OK"
    assert t("decline") == "No thanks"
    assert t("undo") == "Undo"
    assert "English only" in language_directive()


def test_system_prompt_keeps_its_protocol_and_adds_a_language_line(monkeypatch):
    assert SYSTEM.lstrip().startswith("你是辅助型伙伴")
    monkeypatch.setenv("OPENLOOKOUT_LANG", "en")
    system = make_profile().prompts.system
    assert system.startswith(language_directive())
    assert "你是辅助型伙伴" in system
    assert "English only" in system
    monkeypatch.setenv("OPENLOOKOUT_LANG", "zh_TW")
    system = make_profile().prompts.system
    assert system.startswith("对用户说话时只用中文")
    assert "你是辅助型伙伴" in system.split("\n\n", 1)[1]
