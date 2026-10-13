from sprite import sim, pixels, gui
from sprite.decide import Brain


def _run(mk):
    name, say, st, home = sim.run(mk, False, None, mk.__name__)
    return say, home


def test_sunk_user_optimistic_sprite_holds_then_updates():
    say, _ = _run(sim.sc_sunk)
    topics = [x["topic"] for x in say]
    assert topics.count("disagree") == 1            # 不同意只说一次，不唠叨
    assert "hold" in topics and topics.index("hold") > topics.index("disagree")
    assert topics[-1] == "update"                    # 新证据出现后才改口
    d = next(x for x in say if x["topic"] == "disagree")
    assert "不太一样" in d["text"] or "不同意" in d["text"]
    assert "90%" in d["text"] or "%" in d["text"]    # 说出置信度


def test_controls_have_no_fork_style_prompts():
    for mk in (sim.sc_control_productive, sim.sc_control_scattered):
        say, _ = _run(mk)
        assert not [x for x in say if x["topic"] in ("challenge", "disagree", "offer_help", "hold", "update")], mk.__name__


def test_agreeing_user_gets_no_disagreement():
    say, _ = _run(sim.sc_control_productive)
    assert say == []


def test_outside_opinion_is_only_evidence():
    say, home = _run(sim.sc_outside_conflict)
    assert [x["topic"] for x in say] == ["disagree"]
    assert (home / "judgments.jsonl").exists()


def test_actions_reported_in_context_once():
    say, _ = _run(sim.sc_helper)
    assert [x["topic"] for x in say] == ["report", "report"]


def test_dismissals_reduce_speaking():
    a, _ = _run(sim.sc_sunk); b, _ = _run(sim.sc_dismiss)
    assert len(b) <= len(a)


def test_pixels_states_distinct():
    sets = {s: frozenset(pixels.render(s, 1)) for s in pixels.STATES}
    assert len(set(sets.values())) == 4
    assert frozenset(pixels.render("idle", 1, blink=True)) != sets["idle"]


def test_bubble_layout_anchored_and_tail_points_at_sprite():
    g = gui.layout(200, 40, 150, 1920, 1500)
    x0, y0, x1, y1 = g["bubble"]
    assert g["side"] == "left" and x1 < 0 and -x1 <= gui.TAIL + 1          # 紧贴精灵
    assert max(p[0] for p in g["tail"]) > x1                                # 尾尖伸向精灵
    g2 = gui.layout(200, 40, 150, 1920, 20)                                 # 靠左缘则放右边
    assert g2["side"] == "right" and min(p[0] for p in g2["tail"]) < g2["bubble"][0] + 1
