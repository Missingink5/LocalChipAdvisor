"""Tests for the conversation state machine."""
from __future__ import annotations

from local_chip_advisor.mvp.contracts import UserTurn, gen_id
from local_chip_advisor.mvp.conversation import (
    apply_turn, new_session_state,
)


def _turn(text: str) -> UserTurn:
    return UserTurn(turn_id=gen_id("t"), text=text)


def test_bare_product_inherits_pending_question():
    state = new_session_state(gen_id("s"))
    decision = apply_turn(state, _turn("MP4570 太热会自己停吗？"))
    assert decision.intent is not None
    assert decision.intent.product_ids == ["MP4570"]
    state = decision.state

    decision = apply_turn(state, _turn("MP4570"))
    assert decision.clarification is None
    assert decision.intent is not None
    assert decision.intent.product_ids == ["MP4570"]
    # Topic is inherited from the first question
    assert decision.intent.topic == "thermal_shutdown"


def test_missing_product_triggers_clarification():
    state = new_session_state(gen_id("s"))
    decision = apply_turn(state, _turn("太热会自己停吗？"))
    assert decision.clarification is not None
    assert decision.clarification.reason == "missing_product"


def test_three_options_first_picks_first():
    state = new_session_state(gen_id("s"))
    decision = apply_turn(state, _turn("MP4570 怎么样？"))
    assert decision.clarification is not None
    assert any(opt.option_id == "opt_topic_thermal" for opt in decision.clarification.options)
    state = decision.state

    decision = apply_turn(state, _turn("第一项"))
    assert decision.intent is not None
    assert decision.intent.topic == "thermal_shutdown"


def test_three_options_second_picks_second():
    state = new_session_state(gen_id("s"))
    decision = apply_turn(state, _turn("MP4570 怎么样？"))
    state = decision.state
    decision = apply_turn(state, _turn("第二项"))
    assert decision.intent is not None
    assert decision.intent.topic == "soft_start"


def test_vague_reply_does_not_silently_pick_first():
    """'对' alone (when multiple options exist) must NOT pick the first."""
    state = new_session_state(gen_id("s"))
    decision = apply_turn(state, _turn("MP4570 怎么样？"))
    state = decision.state
    decision = apply_turn(state, _turn("对"))
    # When the user just says '对' and we have multiple options, we MUST keep
    # the conversation in AWAITING_CLARIFICATION (no silent first-option pick).
    assert decision.clarification is not None


def test_new_topic_resets_pending_clarification():
    state = new_session_state(gen_id("s"))
    decision = apply_turn(state, _turn("MP4570 怎么样？"))
    assert decision.clarification is not None
    state = decision.state
    decision = apply_turn(state, _turn("TPS54331 软启动怎么设置？"))
    assert decision.clarification is None
    assert decision.intent is not None
    assert decision.intent.product_ids == ["TPS54331"]
    assert decision.intent.topic == "soft_start"


def test_two_products_needs_topic_clarification():
    state = new_session_state(gen_id("s"))
    decision = apply_turn(state, _turn("MP4570 和 TPS54331 都看看吧"))
    # Two products with no clear topic — the user must specify what aspect
    # they want to compare. This is a clarification, not an intent.
    assert decision.clarification is not None
    assert decision.intent is None


def test_explicit_option_id_resolves():
    state = new_session_state(gen_id("s"))
    decision = apply_turn(state, _turn("MP4570 怎么样？"))
    assert decision.clarification is not None
    state = decision.state
    decision = apply_turn(
        state, _turn(""),
        selected_option_id="opt_topic_thermal",
    )
    assert decision.intent is not None
    assert decision.intent.topic == "thermal_shutdown"


def test_new_session_state_is_idle():
    state = new_session_state(gen_id("s"))
    assert state.phase == "IDLE"
    assert state.pending_clarification is None
