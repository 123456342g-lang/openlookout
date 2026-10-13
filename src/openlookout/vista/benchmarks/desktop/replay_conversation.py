"""Replay synthetic dialogue through the configured model without showing it in the GUI."""
from __future__ import annotations

import io
import json
import time
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch

from PIL import Image

from sprite.proactive import conversation, help as helpmod
from sprite.proactive.provider import load_provider
from vista.core.contracts import Visual
from vista.core.profiles import Phase
from vista.core.runtime import TaskRuntime
from . import brain, session as sessionmod
from .profiles import VISTA_TOOLS, make_experiment, make_profile


def run() -> None:
    provider = load_provider()
    directory = brain.HOME / "conversation_replay" / time.strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), "white").save(buffer, "JPEG")
    visual = Visual("screen", "synthetic-screen", buffer.getvalue(), 320, 200, mime_type="image/jpeg")
    now = time.time()
    rows = [
        {"role": "assistant", "text": "他说自己有时两周什么都不想做，放在高效工作这一章有点反讽。", "t": now - 2},
        {"role": "user", "id": "replay-question-1", "text": "为什么叫反讽？我觉得就是挺坦诚的。", "t": now - 1},
    ]
    results = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(conversation, "history", lambda limit=80: rows[-limit:]))
        stack.enter_context(patch.object(sessionmod, "CURRENT", directory / "current.json"))
        stack.enter_context(patch.object(helpmod, "DIR", directory))
        stack.enter_context(patch.object(helpmod, "OFFER", directory / "offer.json"))
        stack.enter_context(patch.object(helpmod, "OFFER_LOG", directory / "offers.jsonl"))
        profile = replace(make_profile(), tools=VISTA_TOOLS + ("companion",))
        session = sessionmod.DesktopSession("合成对话回放。空白图没有桌面活动；仅依据提供的对话接话。", {}, visual=visual)
        experiment = make_experiment(profile, backend="claude", model=provider.model, effort="low",
                                     revision="conversation-replay", presentation={})
        runtime = TaskRuntime(session, experiment, artifact_dir=directory / "artifacts")
        backend = brain.VisualDirectBackend({"model": provider.model, "base_url": provider.base_url,
                                            "api_key": provider.api_key}, runtime)
        backend.attach(session)
        try:
            for phase in (Phase.INITIAL, Phase.STEP):
                started = time.perf_counter()
                before = len(session.decisions)
                reply = backend.run(runtime.prepare_input(phase, public_text=brain.conversation_fact(
                    idle_s=0, now=time.time())))
                decision = session.decisions[-1] if len(session.decisions) > before else {}
                result = {"user": rows[-1]["text"], "reply": decision.get("say"),
                          "reply_to": decision.get("reply_to"), "boundary": reply.boundary,
                          "elapsed_s": round(time.perf_counter() - started, 1)}
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if decision.get("say"):
                    rows.append({"role": "assistant", "text": decision["say"],
                                 "reply_to": decision.get("reply_to"), "t": time.time()})
                if phase == Phase.INITIAL:
                    rows.append({"role": "user", "id": "replay-question-2", "text":
                                 "嗯，我更好奇的是，没动力的时候，先做一点会不会反而有动力？", "t": time.time()})
        finally:
            runtime.close()
    (directory / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    run()
