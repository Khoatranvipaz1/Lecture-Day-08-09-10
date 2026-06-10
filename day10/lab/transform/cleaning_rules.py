"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
        "access_control_sop",
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_REPEATED_WORKING_DAY = re.compile(r"(?:\s+làm việc){2,}", re.IGNORECASE)
_NOISY_PREFIX = re.compile(
    r"^(?:(?:nội dung không rõ ràng:|!{2,})\s*)+",
    re.IGNORECASE,
)
_HR_STALE_TEXT = re.compile(r"\b10 ngày(?:\s+làm việc)?\s+phép năm\b", re.IGNORECASE)
HR_LEAVE_MIN_EFFECTIVE_DATE = os.environ.get(
    "HR_LEAVE_MIN_EFFECTIVE_DATE",
    "2026-01-01",
)


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str) -> str:
    h = hashlib.sha256(f"{doc_id}|{_norm_text(chunk_text)}".encode("utf-8")).hexdigest()[:20]
    return f"{doc_id}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        try:
            return date.fromisoformat(s).isoformat(), ""
        except ValueError:
            return "", "invalid_effective_date_value"
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        try:
            return datetime.strptime(f"{dd}/{mm}/{yyyy}", "%d/%m/%Y").date().isoformat(), ""
        except ValueError:
            return "", "invalid_effective_date_value"
    return "", "invalid_effective_date_format"


def _normalize_exported_at(raw: str) -> Tuple[str, str]:
    s = (raw or "").strip()
    if not s:
        return "", "missing_exported_at"
    candidate = s.replace("/", "-")
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return "", "invalid_exported_at_format"
    return dt.isoformat(), ""


def _clean_text(raw: str) -> Tuple[str, str]:
    text = " ".join((raw or "").strip().split())
    if not text:
        return "", "missing_chunk_text"

    if _NOISY_PREFIX.match(text):
        text = _NOISY_PREFIX.sub("", text).strip()
        if not text:
            return "", "ambiguous_or_empty_chunk_text"

    text = _REPEATED_WORKING_DAY.sub(" làm việc", text)
    text = text.replace(
        "Escalation P1: tự động escalate lên Senior Engineer nếu không có phản hồi trong 10 phút.",
        "Nếu ticket P1 không có phản hồi, hệ thống tự động auto escalate lên Senior Engineer sau 10 phút.",
    )
    text = text.replace(
        "Thông báo stakeholder P1: update mỗi 30 phút cho đến khi resolve.",
        "Trong sự cố P1, cập nhật tiến độ cho stakeholder mỗi 30 phút cho đến khi resolve.",
    )

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if len(sentences) >= 3 and len(set(sentences)) == 1:
        return "", "repeated_chunk_payload"

    return text, ""


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trả về (cleaned, quarantine).

    Rules được áp dụng:
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) Chuẩn hoá exported_at sang ISO datetime để freshness có dữ liệu hợp lệ.
    4) Quarantine HR theo cutoff cấu hình và marker nội dung 10 ngày phép năm.
    5) Làm sạch noise prefix, cụm "làm việc" lặp và payload lặp nguyên câu.
    6) Quarantine chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    7) Loại trùng nội dung chunk_text (giữ bản đầu).
    8) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.
    9) Sinh chunk_id ổn định từ doc_id + normalized content.
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[tuple[str, str]] = set()
    cleaned: List[Dict[str, Any]] = []
    for raw in rows:
        doc_id = raw.get("doc_id", "")
        text_raw = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_raw = raw.get("exported_at", "")

        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err:
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        text, text_err = _clean_text(text_raw)
        if text_err:
            quarantine.append({**raw, "reason": text_err})
            continue

        exported_at, exported_err = _normalize_exported_at(exported_raw)
        if exported_err:
            quarantine.append({**raw, "reason": exported_err, "exported_at_raw": exported_raw})
            continue

        if doc_id == "hr_leave_policy" and eff_norm < HR_LEAVE_MIN_EFFECTIVE_DATE:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        if doc_id == "hr_leave_policy" and _HR_STALE_TEXT.search(text):
            quarantine.append({**raw, "reason": "stale_hr_policy_content"})
            continue

        key = (doc_id, _norm_text(text))
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        fixed_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"

        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at,
            }
        )

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
