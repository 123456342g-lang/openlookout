"""UI language for the resident sprite.

Windows display language (GetUserDefaultUILanguage / locale name) chooses the
catalog: zh* is Chinese, everything else is English. OPENLOOKOUT_LANG overrides
that for the process. Lookups happen when a sentence is shown, so a restart
picks up a new display language. Internal logs are not translated here.
"""
from __future__ import annotations

import ctypes
import locale
import os
from collections.abc import Mapping

_SKIP_POSIX = {"", "c", "posix"}

STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "detail": "详情",
        "undo": "撤销",
        "ok": "好",
        "title": "小精灵",
        "send": "发送",
        "hint": "回车发送 · Esc 关闭",
        "pending_header": "它刚问你的事（没看见的话可以在这里补点）",
        "accept": "好的",
        "decline": "不用",
        "me": "我",
        "sprite": "小精灵",
        "idle_hint": "我在。屏幕上卡住了就点我。",
        "quiet_dialog": "在安静陪着你。屏幕上卡住了，点我聊一句就行。",
        "this_thing": "这件事",
        "timeout_report": "这件事处理超时，我没有留下半截改动。",
        "timeout_say": "这件事花的时间有点长，我先停下了，没有留下半截改动。",
        "start_fail": "这次处理没有启动成功，电脑没有被改动。",
        "errored": "这次处理出错了，我没有留下半截改动。",
        "no_answer_mutations": "这次处理没走到最后一步，我先停下了；已经做了 {n} 处可撤回的改动。",
        "no_answer_clean": "这次处理没走到最后一步，我先停下了，没有改动电脑。",
        "done_default": "已经处理完成。",
        "reclaim_fail": "这次没收起来，电脑没有被改动。",
        "reclaim_fallback": "临时文件、缓存和回收站里能还原的已经收好了，不满意可以还原。",
        "reclaim_empty": "临时文件和缓存已经收进隔离区，随时可以还原。",
        "starting": "好，我开始处理{label}，完成后告诉你。",
        "undo_fail_start": "撤回没有启动成功，请稍后再试。",
        "undo_fail": "撤回没有成功，我没有改动任何其他东西。",
        "batch_all": "按你的同意做了 {total} 件事，随时可以撤回。",
        "batch_partial": "{total} 件事里做成了 {ok} 件，其余没做成；我没有多做别的。",
        "batch_none": "这一批没有做成，电脑状态没有被改动。",
        "rate_limit": "我这会儿连不上，先安静陪着，过几分钟再看你这边。",
        "started_hist": "我开始处理：{text}",
        "expired_hist": "这条提议你没来得及回应，我先作废了，没有动手：{text}",
        "completed_hist": "已完成：{text}",
        "errored_hist": "这次处理出错了，我先停下了，没有留下半截改动。",
        "stopped_hist": "这次处理没有走到最后一步，我先停下了。",
        "undone_hist": "已撤销刚才的改动。",
        "proposal_one": "我想帮你做这件事：\n{line}\n{ask}",
        "proposal_many": "我想帮你做这 {n} 件事：\n{lines}\n{ask}",
        "proposal_start": "要我开始吗？",
        "proposal_together": "要一起做吗？",
        "label_write": "写文档",
        "label_reclaim": "清理临时文件和缓存",
        "label_tidy": "整理桌面文件",
        "label_suspend": "挂起进程",
        "label_end": "结束进程",
        "label_trim": "回收闲置内存",
        "label_undo": "撤回操作",
        "label_shell": "执行命令行",
        "label_capture": "保存证据截图",
        "with_value": "{label}：{value}",
        "tidy_count": "{label}：最多 {n} 个文件",
        "with_pid": "{label}：PID {pid}",
        "undo_recorded": "{label}：撤回本轮已记录的操作",
        "reclaim_none": "没有找到可以安全清理的东西（临时文件、缓存和回收站里都没有可收的项）。电脑没有被改动。",
        "reclaim_cache_count": "{n} 个临时/缓存文件",
        "reclaim_recycle_count": "{n} 项回收站内容",
        "reclaim_summary": "已收进隔离区：{cache}、{recycle}（约 {mb}MB；C 盘 {before}GB → {after}GB，实际腾出 {freed}GB）。{reversible}",
        "reclaim_reversible": "都不是永久删除，点撤销就能原样还原。",
        "reclaim_skipped": "另有 {n} 个状态变了或放不进隔离区，没有动。",
        "reclaim_tight": "安全的来源已经查完，空间还是紧；不确定的用户文件我没有动。",
        "quarantine_empty": "隔离区里没有待还原的东西。",
        "quarantine_restored": "已还原 {n} 个文件到原位置",
        "quarantine_failed": "（{n} 个失败）",
        "quarantine_period": "。",
        "undo_empty": "没有可还原的操作。",
        "undo_none": "没有成功还原的操作。",
        "restored_word": "已还原",
        "undo_done": "已还原：{items}",
        "undo_failed_suffix": "；{n} 个文件因冲突、内容变化或无法处理而保留原处。",
        "list_sep": "；",
        "directive": "对用户说话时只用中文。气泡、提议和回复都用中文。",
    },
    "en": {
        "detail": "Details",
        "undo": "Undo",
        "ok": "OK",
        "title": "Sprite",
        "send": "Send",
        "hint": "Enter to send · Esc to close",
        "pending_header": "It just asked you this (you can answer here if you missed it)",
        "accept": "OK",
        "decline": "No thanks",
        "me": "Me",
        "sprite": "Sprite",
        "idle_hint": "I'm here. Tap me if you're stuck.",
        "quiet_dialog": "I'm here with you. Tap me if you're stuck.",
        "this_thing": "this",
        "timeout_report": "This timed out. I didn't leave a half-finished change.",
        "timeout_say": "This was taking a while, so I stopped. I didn't leave a half-finished change.",
        "start_fail": "This didn't start. The computer was not changed.",
        "errored": "This one ran into an error. I didn't leave a half-finished change.",
        "no_answer_mutations": "This stopped before the last step. I made {n} changes you can undo.",
        "no_answer_clean": "This stopped before the last step. The computer was not changed.",
        "done_default": "Done.",
        "reclaim_fail": "I didn't put anything aside. The computer was not changed.",
        "reclaim_fallback": "Restorable temp files, cache, and recycle-bin items are set aside. You can restore them.",
        "reclaim_empty": "Temp files and cache are set aside and can be restored.",
        "starting": "OK, I'll start on {label} and tell you when it's done.",
        "undo_fail_start": "Undo didn't start. Please try again in a moment.",
        "undo_fail": "Undo didn't finish. I didn't change anything else.",
        "batch_all": "Did {total} things you agreed to. You can undo them.",
        "batch_partial": "Finished {ok} of {total}. The rest didn't get done, and I didn't do anything else.",
        "batch_none": "None of this batch got done. The computer was not changed.",
        "rate_limit": "I can't connect right now. I'll stay quiet and check again in a few minutes.",
        "started_hist": "Starting on this: {text}",
        "expired_hist": "You didn't answer this in time, so I dropped it and didn't change anything: {text}",
        "completed_hist": "Done: {text}",
        "errored_hist": "This one ran into an error. I stopped and didn't leave a half-finished change.",
        "stopped_hist": "This stopped before the last step.",
        "undone_hist": "Undid the last change.",
        "proposal_one": "I'd like to help with this:\n{line}\n{ask}",
        "proposal_many": "I'd like to help with these {n} things:\n{lines}\n{ask}",
        "proposal_start": "Should I start?",
        "proposal_together": "Should I do them together?",
        "label_write": "Write a document",
        "label_reclaim": "Clear temp files and cache",
        "label_tidy": "Tidy desktop files",
        "label_suspend": "Suspend a process",
        "label_end": "End a process",
        "label_trim": "Free idle memory",
        "label_undo": "Undo an action",
        "label_shell": "Run a command",
        "label_capture": "Save an evidence screenshot",
        "with_value": "{label}: {value}",
        "tidy_count": "{label}: up to {n} files",
        "with_pid": "{label}: PID {pid}",
        "undo_recorded": "{label}: undo the changes recorded this turn",
        "reclaim_none": "Nothing safe to clear (no temp files, cache, or recycle-bin items). The computer was not changed.",
        "reclaim_cache_count": "{n} temp/cache files",
        "reclaim_recycle_count": "{n} recycle-bin items",
        "reclaim_summary": "Set aside: {cache} and {recycle} (about {mb}MB; drive C {before}GB → {after}GB, freed {freed}GB). {reversible}",
        "reclaim_reversible": "Nothing was permanently deleted. Undo puts it back.",
        "reclaim_skipped": " Left {n} alone because they changed or could not be set aside.",
        "reclaim_tight": " I checked every safe source and space is still tight. I left uncertain user files alone.",
        "quarantine_empty": "Nothing in the quarantine left to restore.",
        "quarantine_restored": "Restored {n} files to where they were",
        "quarantine_failed": " ({n} failed)",
        "quarantine_period": ".",
        "undo_empty": "Nothing to undo.",
        "undo_none": "Nothing was restored.",
        "restored_word": "Restored",
        "undo_done": "Restored: {items}",
        "undo_failed_suffix": "; {n} files stayed put because of a conflict, a content change, or an error.",
        "list_sep": "; ",
        "directive": "Language: speak to the user in English only. Bubbles, offers, and replies are English. Do not mix Chinese into anything the user can read.",
    },
}


class LiveText:
    """A user-facing sentence resolved from the catalog at comparison time."""

    def __init__(self, key: str) -> None:
        self.key = key

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LiveText):
            return self.key == other.key
        return t(self.key) == other

    def __hash__(self) -> int:
        return hash(("live-text", self.key))

    def __str__(self) -> str:
        return t(self.key)

    def __repr__(self) -> str:
        return t(self.key)


def _from_tag(value: str | None) -> str:
    token = str(value or "").strip().lower().replace("_", "-")
    token = token.split(".", 1)[0].strip()
    if token.startswith("zh"):
        return "zh"
    return "en"


def _from_langid(langid: int) -> str:
    # LANG_CHINESE is primary language id 0x04 (zh-CN, zh-TW, zh-HK, ...).
    if (int(langid) & 0x3FF) == 0x04:
        return "zh"
    return "en"


def _query_windows_ui() -> tuple[int, str]:
    kernel32 = ctypes.windll.kernel32
    langid = int(kernel32.GetUserDefaultUILanguage())
    buf = ctypes.create_unicode_buffer(85)
    # LOCALE_SNAME = 0x0000005C
    written = int(kernel32.GetLocaleInfoW(langid, 0x5C, buf, len(buf)))
    name = buf.value if written > 0 else ""
    return langid, name


def windows_ui_language(*, langid: int | None = None, locale_name: str | None = None) -> str:
    """Map a Windows UI language to zh or en.

    A locale name from GetLocaleInfoW wins. An empty name falls back to the
    LANGID from GetUserDefaultUILanguage.
    """
    if langid is None and locale_name is None:
        langid, locale_name = _query_windows_ui()
    if locale_name:
        return _from_tag(locale_name)
    if langid is None:
        return "en"
    return _from_langid(langid)


def _process_locale_name() -> str:
    try:
        found = locale.getlocale()
    except Exception:
        return ""
    if not found or not found[0]:
        return ""
    return str(found[0])


def posix_ui_language(environ: Mapping[str, str] | None = None, *, process_locale: str | None = None) -> str:
    env = os.environ if environ is None else environ
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        raw = str(env.get(key) or "").strip()
        if raw.lower() not in _SKIP_POSIX:
            return _from_tag(raw)
    name = _process_locale_name() if process_locale is None else process_locale
    if name:
        return _from_tag(name)
    return "en"


def ui_language(
    environ: Mapping[str, str] | None = None,
    *,
    locale_name: str | None = None,
    langid: int | None = None,
    process_locale: str | None = None,
) -> str:
    """zh or en for this process.

    OPENLOOKOUT_LANG wins when it is non-blank. Otherwise Windows uses the
    UI language, and other systems use LC_ALL / LC_MESSAGES / LANG, then the
    process locale. zh* (and Windows primary language 0x04) is Chinese.
    """
    env = os.environ if environ is None else environ
    override = env.get("OPENLOOKOUT_LANG")
    if override is not None and str(override).strip():
        return _from_tag(str(override))
    if locale_name is not None or langid is not None:
        return windows_ui_language(langid=langid, locale_name=locale_name or "")
    if os.name == "nt":
        return windows_ui_language()
    return posix_ui_language(env, process_locale=process_locale)


def _template(lang: str, key: str) -> str:
    catalog = STRINGS.get(lang) or STRINGS["en"]
    if key in catalog:
        return catalog[key]
    if key in STRINGS["en"]:
        return STRINGS["en"][key]
    return key


def t(key: str, /, **kwargs: object) -> str:
    """User-facing string. Missing keys fall back to English, then to the key."""
    template = _template(ui_language(), key)
    if not kwargs:
        return template
    return template.format(**kwargs)


def language_directive() -> str:
    """One line prepended to the model system prompt. It does not replace it."""
    return t("directive")
