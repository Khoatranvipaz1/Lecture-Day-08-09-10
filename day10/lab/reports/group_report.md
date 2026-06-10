# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** Day 10 Data Team
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Khoa | Ingestion, Cleaning/Quality, Embed, Monitoring/Docs | N/A |

**Ngày nộp:** 2026-06-10
**Repo:** local workspace
**Độ dài khuyến nghị:** 600–1000 từ

---

> **Nộp tại:** `reports/group_report.md`  
> **Deadline commit:** xem `SCORING.md` (code/trace sớm; report có thể muộn hơn nếu được phép).  
> Phải có **run_id**, **đường dẫn artifact**, và **bằng chứng before/after** (CSV eval hoặc screenshot).

---

## 1. Pipeline tổng quan (150–200 từ)

> Nguồn raw là gì (CSV mẫu / export thật)? Chuỗi lệnh chạy end-to-end? `run_id` lấy ở đâu trong log?

**Tóm tắt luồng:**

Pipeline ingest 247 dòng CSV, normalize schema/text, tách 214 dòng quarantine,
validate 10 expectations rồi publish 33 chunk vào Chroma. Mỗi run ghi log,
cleaned/quarantine CSV và manifest chứa `run_id`, volume, source timestamp và
publish timestamp. Natural key là hash ổn định của `doc_id + normalized text`;
upsert kèm prune biến collection thành snapshot idempotent.

**Lệnh chạy một dòng (copy từ README thực tế của nhóm):**

`.venv\Scripts\python.exe etl_pipeline.py run --run-id final-good`

---

## 2. Cleaning & expectation (150–200 từ)

> Baseline đã có nhiều rule (allowlist, ngày ISO, HR stale, refund, dedupe…). Nhóm thêm **≥3 rule mới** + **≥2 expectation mới**. Khai báo expectation nào **halt**.

### 2a. Bảng metric_impact (bắt buộc — chống trivial)

| Rule / Expectation mới (tên ngắn) | Trước (số liệu) | Sau / khi inject (số liệu) | Chứng cứ (log / CSV / commit) |
|-----------------------------------|------------------|-----------------------------|-------------------------------|
| Allow `access_control_sop` + source coverage | thiếu 1 source | 5/5 source present | `manifest_final-good.json` |
| HR stale theo content/cutoff | expectation HR fail | 7 stale-content + 19 stale-date quarantine | `quarantine_final-good.csv` |
| Normalize noise/repeated payload | marker/payload có thể publish | 4 row ambiguous/repeated bị quarantine | `quarantine_final-good.csv` |
| Stable IDs + uniqueness gate | ID phụ thuộc sequence | 33 unique IDs, rerun ổn định | `test_pipeline.py` |
| Pydantic cleaned contract | custom checks rời rạc | 33/33 rows validate, 0 errors | `run_final-good.log` |
| Refund expectation inject | pass ở run chuẩn | fail 1 violation khi inject | `run_inject-bad.log` |
| Refund corruption gate | eval inject 20/21 | eval clean 21/21 | hai CSV eval |

**Rule chính (baseline + mở rộng):**

- Allowlist 5 nguồn, normalize effective date và exported timestamp.
- Quarantine missing fields, unknown source, HR version cũ và repeated payload.
- Dedupe nội dung, sửa stale refund 14 thành 7 ngày, normalize operational text.
- Pydantic validate date/datetime, required fields, min length và cấm extra field.
- Halt khi thiếu source, stale refund/HR, ID trùng, datetime sai hoặc còn noise.

**Ví dụ 1 lần expectation fail (nếu có) và cách xử lý:**

Run `inject-bad` fail `refund_no_stale_14d_window` với 1 violation. Đây là
expected behavior; `--skip-validate` chỉ dùng để tạo evidence xấu. Run chuẩn
không có expectation fail.

---

## 3. Before / after ảnh hưởng retrieval hoặc agent (200–250 từ)

> Bắt buộc: inject corruption (Sprint 3) — mô tả + dẫn `artifacts/eval/…` hoặc log.

**Kịch bản inject:**

Tắt refund fix và cố ý bỏ halt để publish context 14 ngày.

**Kết quả định lượng (từ CSV / bảng):**

Run inject đạt 20/21; `q_refund_window` có `hits_forbidden=yes`. Sau fix đạt
21/21, còn grading chính thức đạt 10/10. Pipeline upsert, verify đủ 33 IDs rồi
prune 1 ID stale. HR 12 ngày và Access Control Level 4 đều đúng top-1.

---

## 4. Freshness & monitoring (100–150 từ)

> SLA bạn chọn, ý nghĩa PASS/WARN/FAIL trên manifest mẫu.

SLA source là 24 giờ. Manifest `final-good` báo FAIL vì export mới nhất
2026-04-10 đã cũ hơn 1.400 giờ vào 2026-06-10; publish boundary gần 0 giờ.
Runbook phân biệt upstream stale với job publish vừa chạy.

---

## 5. Liên hệ Day 09 (50–100 từ)

> Dữ liệu sau embed có phục vụ lại multi-agent Day 09 không? Nếu có, mô tả tích hợp; nếu không, giải thích vì sao tách collection.

Collection `day10_kb` tách biệt Day 09 để grading không ảnh hưởng agent cũ.
Multi-agent có thể tái sử dụng snapshot bằng cách trỏ retrieval worker sang
collection này sau khi quality gate pass.

---

## 6. Rủi ro còn lại & việc chưa làm

- Chưa dùng atomic alias swap.
- Chưa có source watermark thật và alert integration.
- Model embedding nhỏ vẫn cần golden eval trong CI.

## 7. Peer review

- Rerun không duplicate vì stable `chunk_id`, upsert và prune.
- Freshness đo watermark từng source, source cũ nhất và `published_at`.
- Record bị flag vào quarantine CSV có reason, Data Owner approve trước rerun.
