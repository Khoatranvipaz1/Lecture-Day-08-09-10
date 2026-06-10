# Quality Report - Day 10

**run_id:** `final-good`
**Ngày:** 2026-06-10

## 1. Tóm tắt

| Chỉ số | Inject bad | Sau fix |
|--------|------------|---------|
| raw_records | 247 | 247 |
| cleaned_records | 33 | 33 |
| quarantine_records | 214 | 214 |
| Expectation halt | Có: stale refund | Không |
| Eval pass | 20/21 | 21/21 |
| Grading pass | Chưa dùng làm final | 10/10 |

Quarantine chính: 109 unknown source, 59 duplicate text, 19 HR cũ theo ngày,
10 missing text, 7 HR cũ theo nội dung, 6 missing effective date, 2 repeated
payload và 2 ambiguous/empty sau khi bỏ noise.

## 2. Before/after retrieval

Artifact: `artifacts/eval/after_inject_bad.csv` và
`artifacts/eval/after_fix.csv`.

- `q_refund_window` trước fix: `contains_expected=yes`,
  `hits_forbidden=yes`. Sau fix: `contains_expected=yes`,
  `hits_forbidden=no`, top-1 là `policy_refund_v4`.
- `q_p1_escalation` và `q_p1_update_frequency` được cải thiện bằng chuẩn hóa
  phrasing vận hành; sau fix cả hai có expected keyword và đúng top-1 source.
- HR 2026 và Access Control đều pass, không còn context 10 ngày phép năm.

## 3. Freshness

SLA là 24 giờ. Pipeline ghi watermark riêng cho năm nguồn và dùng watermark cũ
nhất để quyết định SLA. Cả năm source hiện có watermark
`2026-04-10T00:00:00`, cũ hơn 1.400 giờ tại thời điểm chạy. Publish boundary có
`publish_age_hours=0`, chứng minh snapshot vừa được tạo. Đây là incident upstream
freshness, không phải job publish bị treo.

## 4. Corruption inject

Run `inject-bad` dùng `--no-refund-fix --skip-validate`. Expectation
`refund_no_stale_14d_window` fail nhưng demo vẫn embed để tạo bằng chứng. Eval
phát hiện forbidden context 14 ngày. Run chuẩn publish 33 stable IDs. Cả hai run
đều có `pydantic_cleaned_schema_contract OK`,
`embed_verify count=33` và `embed_snapshot_count=33`; pipeline thực tế upsert,
verify rồi mới prune.

## 5. Hạn chế

- Chưa có staging collection + atomic alias swap.
- Freshness chưa đọc watermark trực tiếp từ source system.
- Embedding model nhẹ cần regression eval để kiểm soát semantic ranking.
