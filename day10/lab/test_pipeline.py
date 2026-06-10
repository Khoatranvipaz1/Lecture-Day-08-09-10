import argparse
from pathlib import Path

import pytest

from evaluation_utils import load_questions, positive_int
from monitoring.freshness_check import check_manifest_freshness
from quality.expectations import run_expectations
from quality.schema import validate_cleaned_rows
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


def test_cleaning_rejects_invalid_calendar_date() -> None:
    cleaned, quarantine = clean_rows(
        [
            {
                "doc_id": "policy_refund_v4",
                "chunk_text": "Nội dung hợp lệ đủ dài để kiểm tra ngày.",
                "effective_date": "2026-02-30",
                "exported_at": "2026-04-10T00:00:00",
            }
        ]
    )

    assert cleaned == []
    assert quarantine[0]["reason"] == "invalid_effective_date_value"


def test_dedupe_is_scoped_to_document() -> None:
    shared_text = "Nội dung giống nhau nhưng thuộc hai tài liệu canonical khác nhau."
    cleaned, quarantine = clean_rows(
        [
            {
                "doc_id": "policy_refund_v4",
                "chunk_text": shared_text,
                "effective_date": "2026-02-01",
                "exported_at": "2026-04-10T00:00:00",
            },
            {
                "doc_id": "sla_p1_2026",
                "chunk_text": shared_text,
                "effective_date": "2026-01-15",
                "exported_at": "2026-04-10T00:00:00",
            },
        ]
    )

    assert len(cleaned) == 2
    assert quarantine == []


def test_pydantic_contract_rejects_invalid_cleaned_row() -> None:
    errors = validate_cleaned_rows(
        [
            {
                "chunk_id": "",
                "doc_id": "policy_refund_v4",
                "chunk_text": "short",
                "effective_date": "not-a-date",
                "exported_at": "not-a-datetime",
            }
        ]
    )

    assert any("chunk_id" in error for error in errors)
    assert any("chunk_text" in error for error in errors)
    assert any("effective_date" in error for error in errors)
    assert any("exported_at" in error for error in errors)


def test_question_loader_rejects_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid questions JSON"):
        load_questions(bad)


def test_question_loader_rejects_missing_question(tmp_path: Path) -> None:
    bad = tmp_path / "bad-shape.json"
    bad.write_text('[{"id": "q1"}]', encoding="utf-8")

    with pytest.raises(ValueError, match="missing a non-empty 'question'"):
        load_questions(bad)


def test_positive_int_rejects_zero() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="must be >= 1"):
        positive_int("0")


def test_freshness_uses_oldest_source_watermark(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """
{
  "latest_exported_at": "2026-06-10T00:00:00+00:00",
  "oldest_source_exported_at": "2026-06-01T00:00:00+00:00",
  "source_watermarks": {
    "new_source": "2026-06-10T00:00:00+00:00",
    "stale_source": "2026-06-01T00:00:00+00:00"
  },
  "published_at": "2026-06-10T00:00:00+00:00"
}
""".strip(),
        encoding="utf-8",
    )

    from datetime import datetime, timezone

    status, detail = check_manifest_freshness(
        manifest,
        sla_hours=24,
        now=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )

    assert status == "FAIL"
    assert detail["source_watermark_at"] == "2026-06-01T00:00:00+00:00"
