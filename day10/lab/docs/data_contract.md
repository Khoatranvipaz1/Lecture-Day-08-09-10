# Data contract — Lab Day 10

> Bắt đầu từ `contracts/data_contract.yaml` — mở rộng và đồng bộ file này.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| Refund policy | CSV export từ policy system | Stale 14 ngày, duplicate | `refund_no_stale_14d_window`, quarantine count |
| SLA P1 | CSV export từ support system | Duplicate, noisy prefix, semantic drift | source coverage, golden eval |
| IT Helpdesk FAQ | CSV export từ knowledge base | Missing text/date, duplicate | non-empty fields, quarantine count |
| HR leave policy | CSV export từ HRIS | Conflict 2025: 10 ngày vs 2026: 12 ngày | HR cutoff + stale-content expectation |
| Access Control SOP | CSV export từ IT Security | Thiếu allowlist, duplicate, missing text | required source coverage |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| chunk_id | string | Có | Stable hash của `doc_id + normalized text`, unique |
| doc_id | string | Có | Thuộc allowlist 5 nguồn canonical |
| chunk_text | string | Có | Tối thiểu 8 ký tự, không marker/noise đã biết |
| effective_date | date | Có | ISO `YYYY-MM-DD` |
| exported_at | datetime | Có | ISO datetime, dùng đo source freshness |

---

## 3. Quy tắc quarantine vs drop

Record lỗi được ghi vào `artifacts/quarantine/quarantine_<run_id>.csv` với cột
`reason`; không silent drop. Data Owner của nguồn sửa upstream hoặc xác nhận
exception, sau đó rerun toàn pipeline. Không merge trực tiếp record quarantine
vào Chroma.

---

## 4. Phiên bản & canonical

Canonical refund là `data/docs/policy_refund_v4.txt`, hiệu lực 2026-02-01 và
cửa sổ 7 ngày làm việc. HR canonical là bản 2026; cutoff đọc từ
`HR_LEAVE_MIN_EFFECTIVE_DATE` (mặc định `2026-01-01`). Năm nguồn hợp lệ được
đồng bộ giữa YAML contract và `ALLOWED_DOC_IDS`.
