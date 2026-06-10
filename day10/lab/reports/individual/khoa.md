# Báo cáo cá nhân - Day 10

**Tên:** Khoa
**Vai trò:** Ingestion, Cleaning/Quality, Embed và Monitoring
**Run chính:** `final-good`
**Run corruption:** `inject-bad`

## 1. Phần phụ trách cụ thể

Tôi phân tích `data/raw/policy_export_dirty.csv` gồm 247 records và phát hiện
`access_control_sop` là nguồn canonical thứ năm nhưng chưa có trong
`ALLOWED_DOC_IDS`. Tôi cập nhật `transform/cleaning_rules.py` để pipeline nhận
đủ năm nguồn, chuẩn hóa `effective_date` và `exported_at`, loại prefix noise,
cụm từ lặp, payload lặp nguyên câu, HR policy cũ và duplicate text. Tôi cũng đổi
`chunk_id` sang hash ổn định của `doc_id + normalized content`, giúp Chroma
upsert idempotent và prune được vector không còn trong snapshot.

Trong `quality/expectations.py`, tôi thêm các quality gate
`required_canonical_sources_present`, `unique_nonempty_chunk_id`,
`exported_at_iso_datetime` và `no_known_noise_markers`. Tôi chạy pipeline,
retrieval eval, grading, freshness check; sau đó hoàn thiện
`contracts/data_contract.yaml`, ba tài liệu trong `docs/`, quality report và
group report.

## 2. Quyết định kỹ thuật

Quyết định quan trọng nhất là dùng severity `halt` cho lỗi có thể làm agent trả
lời sai chính sách: thiếu nguồn canonical, stale refund, HR version cũ, ID trùng
hoặc timestamp không hợp lệ. Rule độ dài chunk chỉ là `warn`, vì một chunk ngắn
không nhất thiết sai fact. Với freshness, tôi tách hai boundary:
`latest_exported_at` đo độ mới của dữ liệu nguồn và `published_at` đo thời điểm
pipeline vừa publish. Nhờ vậy run `final-good` cho thấy job publish vẫn chạy
bình thường dù source upstream đã stale.

## 3. Sự cố và cách xử lý

Khi chạy grading lần đầu, `gq_d10_06` không tìm thấy fact escalation P1 trong
top-5 dù document đúng đã được embed. Kiểm tra top-k cho thấy chunk P2 “90 phút”
đứng cao hơn chunk P1 “10 phút”. Tôi chuẩn hóa câu P1 thành phrasing gần với
truy vấn tự nhiên nhưng giữ nguyên fact. Sau thay đổi, `gq_d10_06` pass và câu
`q_p1_update_frequency` cũng trả đúng top-1 source.

Một lỗi vận hành khác là PowerShell dùng encoding `cp1258`, làm script dừng khi
in ký tự Unicode không hỗ trợ. Tôi đổi log pipeline sang ASCII ở dòng cảnh báo
demo và cấu hình `instructor_quick_check.py` xuất UTF-8. Tôi cũng sửa pipeline
để rerun cùng `run_id` ghi đè log thay vì append, tránh evidence bị lặp.

## 4. Before/after

Run `inject-bad` dùng `--no-refund-fix --skip-validate`. Log ghi
`refund_no_stale_14d_window FAIL`, `violations=1`; eval chỉ đạt 20/21 và
`q_refund_window` có `hits_forbidden=yes`. Run `final-good` tạo 33 cleaned
records, 214 quarantine records, mọi expectation đều pass, eval đạt 21/21 và
grading chính thức đạt 10/10. Manifest ghi `run_id=final-good`; Chroma upsert 33
stable IDs và prune các ID stale từ run trước.

## 5. Cải tiến trong 2 giờ

Tôi sẽ thêm staging collection và atomic alias swap để agent không đọc snapshot
đang publish dở. Đồng thời, tôi sẽ đưa `pytest`, 21 câu retrieval eval và
freshness alert vào CI; build chỉ được promote khi grading 10/10 và source
freshness nằm trong SLA hoặc có exception được Data Owner phê duyệt.
