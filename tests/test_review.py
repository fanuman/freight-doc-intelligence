"""The rules for human review, tested without LangGraph and without a database.

The state below is a clean generated invoice whose first charge amount has been damaged, which is what a
misread looks like: the lines no longer add up to the printed total (a TOTAL_MISMATCH error).
"""
import json

import pytest

from freight_intel.pipeline import nodes, review
from freight_intel.pipeline.validation import validate
from freight_intel.synth.oracle import perfect_extraction
from freight_intel.synth.scenario import build_dataset

CASE = next(c for c in build_dataset(45, 42) if c.error_kind == "CLEAN")
GOOD = perfect_extraction(CASE, "invoice")
BAD = GOOD.model_copy(update={"charges": [GOOD.charges[0].model_copy(update={"amount_text": "1.00"}), *GOOD.charges[1:]]})


def broken_state():
    result = validate("invoice", BAD)
    assert not result.ok  # the setup itself: the damaged invoice really has an error
    return {"doc_type": "invoice", "extraction": BAD, "typed": result.typed, "issues": result.issues,
            "status": "needs_review", "attempts": 3}


def decision(action, **extra):
    return {"action": action, "reviewer": "ana@example.com", **extra}


def scripted(*answers):
    """An `ask` function that gives the answers in order, and records what it was shown."""
    shown, remaining = [], list(answers)

    def ask(request):
        shown.append(request)
        return remaining.pop(0)

    ask.shown = shown
    return ask


# --- parse_decision ------------------------------------------------------------------------

@pytest.mark.parametrize("raw, message", [
    ("approve", "JSON object"),
    ({"action": "maybe", "reviewer": "a"}, "action must be one of"),
    ({"action": "approve"}, "reviewer is required"),
    ({"action": "approve", "reviewer": "  "}, "reviewer is required"),
    ({"action": "approve", "reviewer": "a", "note": "x" * 1001}, "longer than"),
    ({"action": "correct", "reviewer": "a"}, "corrected extraction"),
])
def test_bad_decisions_are_rejected_with_a_readable_message(raw, message):
    with pytest.raises(ValueError, match=message):
        review.parse_decision(raw)


def test_good_decisions_parse():
    d = review.parse_decision(decision("correct", note=" fixed ", extraction=GOOD.model_dump(mode="json")))
    assert (d.action, d.reviewer, d.note) == ("correct", "ana@example.com", "fixed")
    assert review.parse_decision(decision("reject")).extraction is None


# --- what each decision does -----------------------------------------------------------------

def test_the_review_request_is_plain_json():
    request = review.build_review_request(broken_state())
    json.dumps(request)  # raises if anything other than plain values slipped in
    assert request["doc_type"] == "invoice"
    assert any(i["code"] == "TOTAL_MISMATCH" for i in request["issues"])


def test_approving_over_an_error_needs_a_note():
    state = broken_state()
    with pytest.raises(ValueError, match="needs a note"):
        review.apply_decision(state, review.parse_decision(decision("approve")))
    update = review.apply_decision(state, review.parse_decision(decision("approve", note="total is wrong on the paper")))
    assert update["status"] == "reviewed"
    assert update["review"] == {"action": "approve", "reviewer": "ana@example.com", "note": "total is wrong on the paper"}
    assert "issues" not in update  # approving does not hide the findings


def test_reject():
    update = review.apply_decision(broken_state(), review.parse_decision(decision("reject")))
    assert update["status"] == "rejected" and update["review"]["action"] == "reject"


def test_a_good_correction_is_checked_by_the_same_validation_and_passes():
    d = review.parse_decision(decision("correct", extraction=GOOD.model_dump(mode="json")))
    update = review.apply_decision(broken_state(), d)
    assert update["status"] == "reviewed" and update["hint"] == ""
    assert not [i for i in update["issues"] if i.severity == "error"]
    assert update["typed"].charges[0].amount_minor != 100  # the damaged 1.00 is gone


def test_a_wrong_correction_is_caught_by_code_not_trusted():
    wrong = BAD.model_dump(mode="json")  # "correcting" nothing
    update = review.apply_decision(broken_state(), review.parse_decision(decision("correct", extraction=wrong)))
    assert update["status"] == "needs_review"
    assert any(i.code == "TOTAL_MISMATCH" for i in update["issues"])


def test_a_correction_of_the_wrong_shape_raises_value_error():
    d = review.parse_decision(decision("correct", extraction={"charges": "not a list"}))
    with pytest.raises(ValueError):
        review.apply_decision(broken_state(), d)


# --- the ask-until-usable loop -------------------------------------------------------------

def test_loop_returns_on_the_first_usable_answer():
    ask = scripted(decision("reject"))
    assert review.review_loop(broken_state(), ask)["status"] == "rejected"
    assert len(ask.shown) == 1


def test_loop_asks_again_after_an_unusable_answer_and_says_why():
    ask = scripted("yes please", decision("reject"))
    assert review.review_loop(broken_state(), ask)["status"] == "rejected"
    assert "error" not in ask.shown[0]
    assert "JSON object" in ask.shown[1]["error"]


def test_loop_shows_what_remains_after_a_correction_that_still_fails():
    ask = scripted(decision("correct", extraction=BAD.model_dump(mode="json")),
                   decision("approve", note="document's own total is wrong"))
    update = review.review_loop(broken_state(), ask)
    assert update["status"] == "reviewed" and len(ask.shown) == 2
    assert any(i["code"] == "TOTAL_MISMATCH" for i in ask.shown[1]["issues"])


def test_loop_gives_up_after_the_round_limit_but_keeps_the_latest_correction():
    still_wrong = decision("correct", extraction=BAD.model_dump(mode="json"))
    ask = scripted(*[still_wrong] * review.MAX_ROUNDS)
    update = review.review_loop(broken_state(), ask)
    assert update["status"] == "needs_review" and "not completed" in update["error"]
    assert update["extraction"] is not None and update["review"]["action"] == "correct"


def test_loop_is_repeatable_which_the_graph_relies_on():
    """After a pause the graph runs the loop again from the top with the same answers. Same result."""
    answers = ["garbage", decision("correct", extraction=BAD.model_dump(mode="json")), decision("reject")]
    first = review.review_loop(broken_state(), scripted(*answers))
    second = review.review_loop(broken_state(), scripted(*answers))
    assert first["status"] == second["status"] == "rejected"


# --- routing --------------------------------------------------------------------------------

def test_router_sends_unresolved_errors_to_review_and_clean_documents_to_the_end():
    base = {"doc_type": "invoice", "hint": "", "attempts": 1}
    assert nodes.route_after_validate({**base, "status": "needs_review"}) == "review"
    assert nodes.route_after_validate({**base, "status": "ok"}) == "end"
    retry = {**base, "hint": "x", "status": "needs_review"}
    assert nodes.route_after_validate(retry) == "extract_invoice"  # retries come first
    assert nodes.route_after_validate({**retry, "attempts": nodes.MAX_RETRIES + 1}) == "review"


def test_a_correction_made_in_an_earlier_round_survives_a_later_approval():
    """Round 1 improves the reading but it still has an error; round 2 approves it. The approved reading is the
    corrected one, not the model's original."""
    better = GOOD.model_copy(update={"charges": [GOOD.charges[0].model_copy(update={"amount_text": "2.00"}), *GOOD.charges[1:]]})
    ask = scripted(decision("correct", extraction=better.model_dump(mode="json")),
                   decision("approve", note="the document's own total is wrong"))
    update = review.review_loop(broken_state(), ask)
    assert update["status"] == "reviewed" and update["review"]["action"] == "approve"
    assert update["extraction"] == better  # fails before the fix: the original BAD extraction comes back
    assert update["typed"].charges[0].amount_minor == 200
