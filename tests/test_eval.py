"""The scoreboard itself must be trustworthy before we trust any number it prints.

Two checks: a perfect pretend-model scores 100%, and a damaged one scores lower in
exactly the places we damaged. If these pass, a bad number on a real run means
the model is bad, not the harness.
"""
import pytest

from freight_intel.evaluation.metrics import score_document
from freight_intel.evaluation.runner import evaluate, format_report
from freight_intel.pipeline import nodes
from freight_intel.pipeline.schemas import InvoiceExtraction
from freight_intel.synth.oracle import OracleLLM
from freight_intel.synth.scenario import build_dataset

CASES = build_dataset(45, 42)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("openpyxl")
    pytest.importorskip("pdfplumber")
    from freight_intel.synth.writer import write_dataset

    out = tmp_path_factory.mktemp("dataset")
    write_dataset(45, 42, out)
    return out


def run_eval(data_dir, llm):
    return evaluate(data_dir, lambda path, tags, meta: nodes.run_sequentially(llm, path), workers=4)


def test_perfect_model_scores_perfectly(data_dir):
    _, s = run_eval(data_dir, OracleLLM(CASES))
    assert s["documents"] == 90
    assert s["classification_accuracy"] == 1.0
    assert s["charge_amount_recall"] == 1.0
    assert s["field_accuracy"] == 1.0
    assert s["charges"]["f1"] == 1.0
    assert s["exact_match_rate"] == 1.0
    # the 5 invoices whose printed total is really wrong are the only ones sent to a human
    assert s["validator"] == {"arithmetic_errors_flagged": "5/5", "false_total_mismatch": "0/40"}
    assert s["status"] == {"ok": 85, "needs_review": 5}
    assert s["prompt_injection"]["documents"] == 7
    assert s["prompt_injection"]["leaked_into_extraction"] == 0
    assert "Classification accuracy" in format_report(s)


def test_dropping_a_charge_lowers_recall_and_creates_false_alarms(data_dir):
    def drop_last_charge_on_invoices(result, case, kind):
        if kind == "invoice":
            result.charges = result.charges[:-1]
        return result

    scores, s = run_eval(data_dir, OracleLLM(CASES, corrupt=drop_last_charge_on_invoices))
    assert s["charges"]["recall"] < 1.0
    report = format_report(s, scores=scores)  # the report must show WHICH charges were lost
    assert "Charge mismatches" in report and "wanted-but-missing" in report
    assert s["charges"]["precision"] == 1.0  # nothing invented, only something missed
    # a correct invoice now fails its own arithmetic: the "misread" case the repair loop will handle
    assert s["validator"]["false_total_mismatch"] != "0/40"
    assert s["by_kind"]["quote"]["charge_f1"] == 1.0  # quotes were untouched


def test_injected_text_copied_into_output_is_counted_as_a_leak(data_dir):
    def obey_the_injection(result, case, kind):
        if kind == "invoice" and case.injection_text:
            result.charges = [*result.charges, type(result.charges[0])(label=case.injection_text, amount_text="0.00")]
        return result

    _, s = run_eval(data_dir, OracleLLM(CASES, corrupt=obey_the_injection))
    assert s["prompt_injection"]["leaked_into_extraction"] == 7
    assert s["prompt_injection"]["exact_match_rate"] == 0.0


def test_failed_document_scores_zero_not_crash():
    truth = {"case_id": "c", "error_kind": "CLEAN", "prompt_injection": False, "injection_text": "",
             "quote": {"carrier_id": "x", "quote_ref": "Q", "issued_on": "2026-01-01", "valid_until": "2026-02-01",
                       "currency": "USD", "charges": [{"raw_label": "Ocean freight", "amount_minor": 100}]}}
    score = score_document("quote", truth, {"status": "failed"}, source_format="pdf")
    assert not score.doc_type_ok and not any(score.fields.values())
    assert (score.charge_tp, score.charge_fn) == (0, 1) and not score.exact


def test_a_basis_suffix_on_the_label_is_a_label_error_not_an_amount_error(data_dir):
    """The real failure from the first OpenAI run: 'O/F' returned as 'O/F per container'."""
    def append_basis(result, case, kind):
        for charge in result.charges:
            charge.label += " per container"
        return result

    _, s = run_eval(data_dir, OracleLLM(CASES, corrupt=append_basis))
    assert s["charges"]["f1"] == 0.0  # strict: every label is wrong
    assert s["charge_amount_recall"] == 1.0  # ...but every amount is right
    assert s["field_accuracy"] == 1.0


def _misread_every_invoice(result, case, kind):
    """A model that reads the first charge of every invoice wrong ('0.01')."""
    if kind == "invoice":
        result.charges[0].amount_text = "0.01"
    return result


def test_repair_loop_fixes_misreads_but_not_documents_that_are_really_wrong(data_dir):
    llm = OracleLLM(CASES, corrupt=_misread_every_invoice, fix_when_hinted=True)
    _, s = run_eval(data_dir, llm)
    # every misread was fixed by the retry...
    assert s["validator"]["false_total_mismatch"] == "0/40"
    assert s["charges"]["f1"] == 1.0
    # ...but the 5 invoices whose printed total is really wrong must still reach a human
    assert s["validator"]["arithmetic_errors_flagged"] == "5/5"
    assert s["status"] == {"ok": 85, "needs_review": 5}
    assert s["repair_loop"] == {"retried": 45, "fixed": 40, "extra_extractions": 40 + 5 * 2}


def test_without_the_hint_a_misreading_model_stays_wrong_after_all_retries(data_dir):
    llm = OracleLLM(CASES, corrupt=_misread_every_invoice, fix_when_hinted=False)
    _, s = run_eval(data_dir, llm)
    assert s["validator"]["false_total_mismatch"] == "40/40"
    assert s["repair_loop"]["fixed"] == 0
    assert s["repair_loop"]["extra_extractions"] == 45 * 2  # each retried exactly twice, then given up
