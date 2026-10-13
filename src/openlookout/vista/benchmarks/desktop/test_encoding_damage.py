"""Encoding-damage regression for brain.py.

A round of GB18030 damage once ate the newline out of the comment on
``CHANGE_MIN``, silently swallowing ``MIN_GAP_S = 5`` into it.  The module still
parsed, all319 tests still passed, and only the live run noticed -- via
``NameError: name 'MIN_GAP_S' is not defined`` raised from inside the step
loop, after which the supervisor relaunched brain every few seconds forever.
No user-facing symptom appeared except that the sprite stopped talking for
hours.

So: this file does not test behaviour.  It asserts that no statement was ever
absorbed into a comment, and that the module-level tunables survived intact.
"""
import ast
import pathlib

import pytest

from vista.benchmarks.desktop import brain

SOURCE = pathlib.Path(brain.__file__)

# Names the step loop dereferences on every single iteration.  If one of these
# is missing the loop raises NameError and the process dies mid-run, so they
# are the ones worth pinning.
RUNTIME_CONSTANTS = ("MIN_GAP_S", "HEARTBEAT_S", "PREP_EVERY_TURNS",
                     "CHANGE_MIN", "ACTIVE_MODEL")


def _module_source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_brain_source_is_not_itself_damaged():
    """A lost byte shows up as U+FFFD or an undecodable file."""
    raw = SOURCE.read_bytes()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - would be obvious
        pytest.fail(f"brain.py is no longer valid utf-8: {exc}")
    assert "\ufffd" not in raw.decode("utf-8"), "brain.py contains U+FFFD"


def test_no_statement_was_absorbed_into_a_comment():
    """The exact failure mode: ``# comment<newline>NAME = value`` -> ``# commentNAME = value``.

    Recovering those by hand is guesswork; catching them mechanically is not.
    """
    glued = []
    for lineno, line in enumerate(_module_source().splitlines(), 1):
        hash_at = line.find("#")
        if hash_at < 0:
            continue
        comment = line[hash_at:]
        for name in RUNTIME_CONSTANTS:
            # ``NAME =`` sitting inside a comment, not preceded by prose
            if f"# {name} =" in comment or comment.endswith(f"#{name} ="):
                glued.append(f"{lineno}: {line.strip()}")
    assert not glued, "assignment swallowed by a comment:\n" + "\n".join(glued)


def test_every_runtime_constant_is_defined_at_module_level():
    """The loop reads these as globals; a missing one is a mid-run NameError."""
    defined = set()
    for node in ast.parse(_module_source()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
    missing = [n for n in RUNTIME_CONSTANTS if n not in defined]
    assert not missing, f"not assigned at module level: {missing}"


@pytest.mark.parametrize("name", RUNTIME_CONSTANTS)
def test_runtime_constant_is_usable(name):
    value = getattr(brain, name)
    assert value is not None
    if name != "ACTIVE_MODEL":
        assert isinstance(value, (int, float)), f"{name} should stay numeric"


def test_min_gap_stays_short_enough_to_look_reactive():
    """MIN_GAP_S is the floor on how fast the sprite may answer.  It was 5 when
    the damage landed; anything near HEARTBEAT_S means the sprite has gone
    silent again without a single crash to point at it."""
    assert 1 <= brain.MIN_GAP_S <= 30
    assert brain.MIN_GAP_S < brain.HEARTBEAT_S


def test_active_model_is_read_from_the_environment():
    """A hard-coding an alias made the endpoint 400.  The host-native backend
    publishes deepseek-v4.1-flash, and the model must stay overridable."""
    assert brain.ACTIVE_MODEL
    assert any("OPENLOOKOUT_MODEL" in line
               for line in _module_source().splitlines()), \
        "ACTIVE_MODEL must stay overridable via OPENLOOKOUT_MODEL"


def test_turn_timeout_is_companion_length_not_research_length():
    """The claude runner defaults to 3600s per turn.  With that default a single
    turn could outlive the entire conversation -- the model kept probing and the
    sprite said nothing for four hours.  This is the second half of that
    silence, after the swallowed-constant crash."""
    assert 60 <= brain.TURN_TIMEOUT_S <= 400, \
        f"a companion turn must stay short, got {brain.TURN_TIMEOUT_S}s"
    assert brain.TURN_TIMEOUT_S < 3600


def test_turn_timeout_is_actually_passed_to_the_backend():
    """A constant nobody wires up fixes nothing.  Assert the claude backend is
    built with it, so the bound is real rather than decorative."""
    assert "task_timeout=TURN_TIMEOUT_S" in _module_source(), \
        "create_backend must receive task_timeout=TURN_TIMEOUT_S"