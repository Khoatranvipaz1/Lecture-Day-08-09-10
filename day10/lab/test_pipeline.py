from pathlib import Path

import pytest

from eval_retrieval import _load_questions as load_eval_questions
from grading_run import _load_questions as load_grading_questions
from quality.expectations import run_expectations
from transform.cleaning_rules import clean_rows, load_raw_csv


ROOT = Path(__file__).resolve().parent


def test_cleaning_produces_valid_five_source_snapshot() -> None:
    rows = load_raw_csv(ROOT / "data" / "raw" / "policy_export_dirty.csv")
    cleaned, quarantine = clean_rows(rows)
    results, halt = run_expectations(cleaned)

    assert len(rows) == 247
    assert cleaned
    assert quarantine
    assert not halt, [r.detail for r in results if not r.passed]
    assert {r["doc_id"] for r in cleaned} == {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
        "access_control_sop",
    }


def test_cleaning_removes_stale_and_noisy_content() -> None:
    rows = load_raw_csv(ROOT / "data" / "raw" / "policy_export_dirty.csv")
    cleaned, quarantine = clean_rows(rows)
    blob = "\n".join(str(r["chunk_text"]).lower() for r in cleaned)
    reasons = {str(r["reason"]) for r in quarantine}

    assert "14 ngày làm việc" not in blob
    assert "10 ngày phép năm" not in blob
    assert "làm việc làm việc" not in blob
    assert "nội dung không rõ ràng" not in blob
    assert "stale_hr_policy_content" in reasons
    assert "unknown_doc_id" in reasons


def test_chunk_ids_are_stable_across_reruns() -> None:
    rows = load_raw_csv(ROOT / "data" / "raw" / "policy_export_dirty.csv")
    first, _ = clean_rows(rows)
    second, _ = clean_rows(rows)

    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second]


@pytest.mark.parametrize("loader", [load_eval_questions, load_grading_questions])
def test_question_loader_rejects_invalid_json(tmp_path: Path, loader) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid questions JSON"):
        loader(bad)


@pytest.mark.parametrize("loader", [load_eval_questions, load_grading_questions])
def test_question_loader_rejects_missing_question(tmp_path: Path, loader) -> None:
    bad = tmp_path / "bad-shape.json"
    bad.write_text('[{"id": "q1"}]', encoding="utf-8")

    with pytest.raises(ValueError, match="missing a non-empty 'question'"):
        loader(bad)
