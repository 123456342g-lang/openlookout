"""Run one desktop task through a backend. The backend factory decides the transport (Claude Code or Codex)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from vista.core.runtime import BudgetExhausted, TaskRuntime

from .profiles import make_experiment, make_profile
from .session import DesktopSession


def answer_loop(session: DesktopSession, runtime: TaskRuntime, backend: Any) -> None:
    from vista.core.profiles import Phase as P
    try:
        task_input = runtime.prepare_input(P.INITIAL)
        result = backend.run(task_input)
    except BudgetExhausted:
        return
    if runtime.terminal or result.returncode != 0 or runtime.failure:
        return
    if not session.answered and result.final_message:
        runtime.submit(result.final_message)


def run_task(objective: str, context: dict[str, Any], *, directory: Path, backend: str, model: str, effort: str,
             backend_factory: Callable[[TaskRuntime, Path], Any], revision: str = "0.1") -> dict[str, Any]:
    from vista.core.artifacts import ArtifactStore
    root = directory.resolve()
    ArtifactStore(root)
    session = DesktopSession(objective, context)
    profile = make_profile()
    experiment = make_experiment(profile, backend=backend, model=model, effort=effort, revision=revision,
                                 presentation={"objective": objective, "context": context})
    runtime = TaskRuntime(session, experiment, artifact_dir=root / "artifacts")
    backend_session = None
    try:
        backend_session = backend_factory(runtime, root / "transport")
        answer_loop(session, runtime, backend_session)
    finally:
        runtime.close()
    return session.result()
