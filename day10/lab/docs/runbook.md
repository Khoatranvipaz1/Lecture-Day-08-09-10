# Runbook — Lab Day 10 (incident tối giản)

---

## Symptom

Agent trả lời refund là 14 ngày, HR là 10 ngày phép năm, hoặc không tìm được
Access Control Level 4. Một biểu hiện khác là top-1 đúng doc nhưng top-k thiếu
fact cần thiết do chunk noise.

---

## Detection

- `refund_no_stale_14d_window` fail và pipeline halt.
- Eval có `hits_forbidden=yes` hoặc `contains_expected=no`.
- Manifest có source `age_hours > 24`; run `final-good` ngày 2026-06-10 báo
  source FAIL vì export mới nhất là 2026-04-10.
- `publish_age_hours` đo boundary publish; giá trị gần 0 chứng minh job vừa chạy.

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Kiểm tra `artifacts/manifests/*.json` | Xác định run, volume, source/publish freshness |
| 2 | Mở `artifacts/quarantine/*.csv` | Nhóm lỗi theo `reason`, tìm source/version bị loại |
| 3 | Đọc log expectation | Xác định quality gate halt hay warn |
| 4 | Chạy `python eval_retrieval.py` | So sánh câu fail, top-1 và forbidden context |
| 5 | Kiểm tra Chroma count | Count phải bằng `cleaned_records`, không có ID cũ |

---

## Mitigation

Timebox: 0-5 phút kiểm tra freshness, 5-12 phút volume/errors, 12-20 phút
schema/lineage. Mitigation là dừng publish khi expectation fail, rerun snapshot
`final-good`, hoặc rollback collection gần nhất. Nếu source vẫn stale, hiển thị
banner data stale và báo `#data-observability`.

---

## Prevention

Giữ regression eval 21 câu trong CI, alert source freshness 24 giờ, yêu cầu đủ
5 source trước publish, dùng stable key và prune. Production nên publish qua
staging collection + atomic alias swap.

## Trạng thái freshness

- `PASS`: source age <= SLA.
- `WARN`: manifest hoặc timestamp không parse được.
- `FAIL`: manifest thiếu hoặc source age vượt SLA. Pipeline demo vẫn hoàn tất
  để lưu evidence; production phải chặn serving hoặc dùng snapshot gần nhất.
