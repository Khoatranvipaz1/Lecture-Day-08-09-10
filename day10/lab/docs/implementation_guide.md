# Day 10 Implementation Guide

## 1. Mục tiêu

Lab xây dựng data pipeline phục vụ RAG/agent theo luồng:

```text
raw CSV
  -> clean and normalize
  -> quarantine invalid/stale rows
  -> quality gates and Pydantic contract
  -> Chroma upsert
  -> verify target snapshot
  -> prune stale vectors
  -> retrieval eval and grading
```

Pipeline xử lý 247 raw records từ nhiều hệ thống. Run chuẩn `final-good` tạo
33 cleaned chunks và 214 quarantine records. Collection cuối chứa đủ năm nguồn
canonical:

- `policy_refund_v4`
- `sla_p1_2026`
- `it_helpdesk_faq`
- `hr_leave_policy`
- `access_control_sop`

## 2. Thành phần chính

| File | Trách nhiệm |
|------|-------------|
| `etl_pipeline.py` | Điều phối ingest, clean, validate, embed và manifest |
| `transform/cleaning_rules.py` | Chuẩn hóa và phân loại cleaned/quarantine |
| `quality/expectations.py` | Quality gates với severity warn/halt |
| `quality/schema.py` | Pydantic contract cho cleaned rows |
| `monitoring/freshness_check.py` | Đo source freshness và publish freshness |
| `eval_retrieval.py` | Chạy 21 câu retrieval regression |
| `grading_run.py` | Chạy 10 câu grading chính thức |
| `evaluation_utils.py` | Loader, validation và scoring dùng chung |
| `instructor_quick_check.py` | Kiểm format grading JSONL và manifest |

## 3. Cleaning rules

Pipeline áp dụng các rule sau:

1. Chỉ nhận năm `doc_id` canonical; nguồn lạ được quarantine.
2. Chuẩn hóa ngày `DD/MM/YYYY` sang `YYYY-MM-DD`.
3. Chuẩn hóa `exported_at` sang ISO datetime.
4. Loại record thiếu ngày, thiếu text hoặc timestamp không parse được.
5. Loại HR policy trước cutoff `HR_LEAVE_MIN_EFFECTIVE_DATE`.
6. Loại HR content cũ chứa 10 ngày phép năm.
7. Bỏ prefix noise như `Nội dung không rõ ràng:` và `!!!`.
8. Chuẩn hóa cụm `làm việc` bị lặp và quarantine payload lặp nguyên câu.
9. Dedupe theo normalized chunk text.
10. Sửa refund window stale từ 14 thành 7 ngày trong run chuẩn.
11. Sinh `chunk_id` ổn định từ `doc_id + normalized content`.

Mỗi record bị loại được ghi vào quarantine CSV cùng trường `reason`. Pipeline
không silent drop dữ liệu.

## 4. Quality gates

Expectation suite gồm các kiểm tra:

| Expectation | Severity | Ý nghĩa |
|-------------|----------|---------|
| `min_one_row` | halt | Snapshot không được rỗng |
| `no_empty_doc_id` | halt | Mọi row phải có nguồn |
| `refund_no_stale_14d_window` | halt | Không publish refund policy cũ |
| `chunk_min_length_8` | warn | Cảnh báo chunk quá ngắn |
| `effective_date_iso_yyyy_mm_dd` | halt | Ngày hiệu lực đúng schema |
| `hr_leave_no_stale_10d_annual` | halt | Không còn HR policy 2025 |
| `required_canonical_sources_present` | halt | Có đủ năm nguồn |
| `unique_nonempty_chunk_id` | halt | Natural key hợp lệ và unique |
| `exported_at_iso_datetime` | halt | Freshness timestamp parse được |
| `no_known_noise_markers` | halt | Không publish marker migration/noise |
| `pydantic_cleaned_schema_contract` | halt | Cleaned rows đúng contract |

`quality.schema.CleanedChunk` sử dụng Pydantic v2, cấm extra fields và validate
kiểu thật cho `date`, `datetime`, required strings và minimum text length.

## 5. Publish và idempotency

Mỗi chunk dùng stable ID nên rerun cùng dữ liệu không tạo duplicate. Publish
được thực hiện theo thứ tự:

1. Đọc danh sách ID đang có.
2. Upsert toàn bộ target chunks.
3. Đọc lại và verify đủ target IDs.
4. Chỉ sau khi verify thành công mới prune ID stale.

Thứ tự này giảm rủi ro làm mất serving data. Nếu upsert hoặc verify lỗi,
pipeline trả lỗi trước khi xóa ID stale. Đây chưa phải atomic publish: upsert có
thể cập nhật một phần target IDs trước khi lỗi; production vẫn nên dùng staging
collection và alias swap. Log chuẩn ghi:

```text
embed_upsert count=33 collection=day10_kb
embed_verify count=33
embed_prune_removed=1
embed_snapshot_count=33
```

## 6. Exception handling

Các entrypoint bắt lỗi theo stage và trả exit code có kiểm soát:

- Thiếu dependency.
- File câu hỏi không tồn tại hoặc JSON hỏng.
- Question thiếu trường bắt buộc.
- Model hoặc Chroma không khởi tạo được.
- Retrieval query lỗi.
- Không ghi được output.
- Không đọc được cleaned CSV.
- Embed upsert, verify hoặc prune lỗi.

Malformed question JSON được kiểm thử và trả exit code `2`, không in traceback
thô. Pipeline có fallback `PIPELINE_ERROR` và `PIPELINE_UNEXPECTED_ERROR`.

## 7. Cách chạy

Từ thư mục `day10/lab`:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe etl_pipeline.py run --run-id final-good
```

Chạy test và đánh giá:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe eval_retrieval.py --out artifacts\eval\after_fix.csv
.venv\Scripts\python.exe grading_run.py --out artifacts\eval\grading_run.jsonl
.venv\Scripts\python.exe instructor_quick_check.py `
  --grading artifacts\eval\grading_run.jsonl `
  --manifest artifacts\manifests\manifest_final-good.json
```

Tạo evidence corruption:

```powershell
.venv\Scripts\python.exe etl_pipeline.py run `
  --run-id inject-bad `
  --no-refund-fix `
  --skip-validate
.venv\Scripts\python.exe eval_retrieval.py `
  --out artifacts\eval\after_inject_bad.csv
```

## 8. Kết quả đã xác minh

| Chỉ số | Kết quả |
|--------|---------|
| Unit tests | 10/10 pass |
| Raw records | 247 |
| Cleaned records | 33 |
| Quarantine records | 214 |
| Inject retrieval | 20/21 |
| Final retrieval | 21/21 |
| Official grading | 10/10 |
| Pydantic schema errors | 0 |
| Published target IDs | 33/33 |

Run inject fail đúng expectation refund với một violation và
`q_refund_window` có forbidden context 14 ngày. Run final loại context stale,
đạt toàn bộ 21 câu retrieval và 10 câu grading.

## 9. Freshness

Manifest đo hai boundary:

- `source_watermarks`: watermark mới nhất của từng nguồn canonical.
- `oldest_source_exported_at`: watermark cũ nhất, dùng quyết định SLA để một
  nguồn mới không che nguồn khác đang stale.
- `published_at`: thời điểm pipeline publish index.

Manifest còn ghi `published_vectors` và `publish_strategy`; quick-check yêu cầu
`published_vectors == cleaned_records` để phát hiện publish thiếu.

Source mẫu mới nhất là ngày 2026-04-10 nên vượt SLA 24 giờ và trả `FAIL`. Đây
là kết quả đúng, thể hiện upstream source stale. `publish_age_hours` gần 0 tại
thời điểm run cho thấy pipeline vừa publish thành công.

## 10. Artifacts

| Artifact | Đường dẫn |
|----------|-----------|
| Final log | `artifacts/logs/run_final-good.log` |
| Inject log | `artifacts/logs/run_inject-bad.log` |
| Final manifest | `artifacts/manifests/manifest_final-good.json` |
| Inject manifest | `artifacts/manifests/manifest_inject-bad.json` |
| Final eval | `artifacts/eval/after_fix.csv` |
| Inject eval | `artifacts/eval/after_inject_bad.csv` |
| Grading | `artifacts/eval/grading_run.jsonl` |
| Quality report | `docs/quality_report.md` |

## 11. Hạn chế và hướng tiếp theo

- Chroma demo chưa có staging collection và atomic alias swap.
- Freshness chưa đọc watermark trực tiếp từ source systems.
- Model embedding nhẹ vẫn cần golden regression eval.
- Production nên thêm scheduler, alert integration và CI gate.
