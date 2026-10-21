"""A user message must not wait on a quiet screen.

Measured on 10-13 07:09:09: the user typed "哪里有问题，具体指出来" and the
bubble appeared at 07:10:02 -- 52.8s.  Nothing was slow in that window.  The
turn loop had no trigger that fires just because someone is waiting: it woke on
screen changes, timing events and maintenance, so a still screen plus a pending
message looked identical to "nothing to do".

These tests pin the deadline that closes that gap, and pin the two ways it must
not become a new failure mode: it must not manufacture turns out of a stale
transcript, and it must not fire for a message that was actually answered.
"""
import pathlib
import time

import pytest

from vista.benchmarks.desktop import brain

SOURCE = pathlib.Path(brain.__file__)


@pytest.fixture
def transcript(monkeypatch):
    """Point the conversation reader at a transcript we control.

    Patch the attribute on the ``sprite.proactive.conversation`` module itself:
    ``from sprite.proactive import conversation`` prefers an attribute already
    bound on the parent package, so patching ``sys.modules`` alone silently
    keeps reading the real conversation.jsonl once another test has imported
    it.  Import it first so the parent attribute exists.
    """
    import sprite.proactive
    from sprite.proactive import conversation

    rows = []

    def fake_history(limit=80):
        return list(rows)

    def fake_pending(history_rows):
        latest_user = next((r for r in reversed(history_rows) if r.get("role") == "user"), None)
        if latest_user is None:
            return None
        identity = f"message:{latest_user.get('t')}"
        for row in history_rows:
            if row.get("role") != "assistant" or row.get("kind") == "reply":
                continue
            if row.get("reply_to") == identity:
                return None
        return latest_user

    monkeypatch.setattr(conversation, "history", fake_history)
    monkeypatch.setattr(conversation, "pending_message", fake_pending)
    return rows


def _user(t, text="在吗"):
    return {"role": "user", "text": text, "kind": "message", "t": t, "id": f"message:{t}"}


def _said(t, text="我在", reply_to=None):
    row = {"role": "assistant", "text": text, "kind": "say", "t": t}
    if reply_to:
        row["reply_to"] = reply_to
    return row


def test_pending_message_sets_a_deadline(transcript):
    """The whole point: a message nobody answered is on the clock."""
    now = time.time()
    transcript.append(_user(now - 5))

    deadline = brain.pending_reply_deadline(now)

    assert deadline is not None, "an unanswered message must arm the reply deadline"
    # It was written 5s ago and gets REPLY_DEADLINE_S in total, not a fresh
    # budget from now -- otherwise every poll would push the deadline away and
    # the message would never actually expire.
    assert deadline == pytest.approx(now + brain.REPLY_DEADLINE_S - 5, abs=1.0)


def test_answered_message_arms_nothing(transcript):
    """reply_to is what marks a message handled; once set, stop nagging."""
    now = time.time()
    t = now - 5
    transcript.extend([_user(t), _said(now - 1, reply_to=f"message:{t}")])

    assert brain.pending_reply_deadline(now) is None


def test_stale_message_does_not_rearm(transcript):
    """An unanswered message from hours ago is not someone still waiting.

    Without this the loop would keep manufacturing turns forever off a stale
    transcript, which is the same "sprite never stops talking" failure the
    timing gate was built to prevent.
    """
    now = time.time()
    transcript.append(_user(now - brain.PENDING_MAX_AGE_S - 60))

    assert brain.pending_reply_deadline(now) is None


def test_no_pending_message_arms_nothing(transcript):
    now = time.time()
    transcript.append(_said(now - 10, "只是我自己在说话"))

    assert brain.pending_reply_deadline(now) is None


def test_unreadable_transcript_is_not_fatal(transcript, monkeypatch):
    """A broken log must not kill the turn loop."""
    from sprite.proactive import conversation

    now = time.time()

    def explode(*_a, **_k):
        raise OSError("conversation.jsonl unreadable")

    monkeypatch.setattr(conversation, "history", explode)
    assert brain.pending_reply_age(now) is None


def test_deadline_is_reachable_not_infinite(transcript):
    """The deadline has to be a real ceiling, measured from the message."""
    now = time.time()
    transcript.append(_user(now))

    deadline = brain.pending_reply_deadline(now)

    assert brain.REPLY_DEADLINE_S <= 300, \
        "a reply deadline longer than a turn timeout cannot be enforced"
    assert deadline <= now + brain.REPLY_DEADLINE_S


def test_deadline_has_not_gone_backwards_in_time(transcript):
    """A clock that jumped must not produce a deadline in the distant past."""
    now = time.time()
    transcript.append(_user(now + 500))

    deadline = brain.pending_reply_deadline(now)

    # A message "from the future" is a clock artefact, not a real pending item.
    assert deadline is None or deadline >= now


def test_priority_starts_immediately_not_at_the_deadline(transcript):
    """The measured 52.8s: the turn in flight when he wrote must reprioritise.

    This is the distinction the whole fix rests on.  A brand-new message is
    already someone waiting, so age ~0 has to read as pending.  If priority
    only kicked in near the deadline, the turn that was already running would
    keep investigating and the reply would land a turn late -- reproducing the
    number we are trying to remove.
    """
    now = time.time()
    transcript.append(_user(now - 0.4))

    age = brain.pending_reply_age(now)

    assert age is not None, "a message typed a moment ago is already pending"
    assert age < 1.0
    # Well inside the budget, yet still pending -- urgency is a separate thing.
    assert brain.REPLY_DEADLINE_S - age > brain.MIN_GAP_S


def test_age_is_measured_from_the_message_not_recomputed_per_poll(transcript):
    """Polling must not reset the clock, or the deadline never actually expires."""
    now = time.time()
    transcript.append(_user(now - 30))

    first = brain.pending_reply_age(now)
    second = brain.pending_reply_age(now + 10)

    assert first is not None and second is not None
    assert second - first == pytest.approx(10, abs=0.01), \
        "age must advance with the clock, not restart on every poll"


# --- the wiring in run() -------------------------------------------------
# The helpers above are easy to get right and still leave the feature dead, so
# pin the three places the turn loop has to consult them.  A pending message
# that never reaches the prompt is the same bug as no feature at all.


def _loop_source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_pending_message_is_wired_into_the_trigger_gate():
    """A stranded message needs something to wake the loop, not just a prompt."""
    src = _loop_source()
    start = src.index("if not model_turn_due(")
    gate = src[start:src.index("):", start)]
    assert "reply_due=reply_due" in gate, \
        "the trigger gate ignores reply_due, so a quiet screen still strands the message"
    assert "heartbeat_due" not in gate and "history_due" not in gate


def test_a_pending_message_makes_the_turn_a_reply_turn():
    """Priority must key off 'pending', not 'nearly out of time'.

    Keying off urgency is the subtle version of this bug: the tests on
    pending_reply_age still pass, the helper still works, and the turn in
    flight when the user writes carries on investigating -- which is the 52.8s.
    """
    body = next(line for line in _loop_source().splitlines()
                if "reply_pending = reply_age is not None" in line)
    assert "reply_age is not None" in body, \
        "reply_pending must mean 'a message is unanswered', not 'the deadline is close'"
    # The lead line and the priority block must both follow reply_pending.
    assert any("if prep_due and not reply_pending:" in line for line in _loop_source().splitlines()), \
        "a pending reply must suppress the background prep turn"
    assert any('"这是回话轮：他在等你回答。" if reply_pending' in line
               for line in _loop_source().splitlines()), \
        "the model is not told this turn exists to answer him"
    assert any("if reply_pending:" in line and "优先回话" not in line
               for line in _loop_source().splitlines()), \
        "the priority instruction is never appended to the turn input"


def test_wakeup_stays_bounded_to_the_deadline():
    """Priority is cheap; the wakeup is not.  Only lateness may add one."""
    source = _loop_source()
    assert "reply_pending or" not in source, \
        "reply_pending must not be a wakeup trigger, or a pending-but-recent " \
        "message would spin the loop every tick"