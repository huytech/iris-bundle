# Safety Rules

1. Nguồn là folder local do user truyền; chỉ đọc nguồn.
2. Không rename, move, ghi đè hoặc xóa file nguồn.
3. Mọi file phải qua `scan → plan → user confirmation → stage → upload → metadata → verify`.
4. Chỉ nhận mã `ready` từ `cnc-generate-document-code`; không tự phân loại/ghép/sửa mã.
5. `plan` phải hiển thị source, prefix cũ agent quyết định bỏ, mã, tên mới, destination, năm metadata và collision; script không được tự detect prefix cũ.
6. Confirmation là bắt buộc; preview chi tiết phải hiển thị trong chat chính hoặc file preview, còn popup hỏi xác nhận chỉ được là câu ngắn dễ duyệt, không nhồi markdown table dài. Yêu cầu chung “xử lý/upload” không thay thế việc duyệt preview cụ thể.
7. Khi plan thay đổi sau confirmation, confirmation cũ vô hiệu.
8. Stage bằng bản copy trong `.cnc-staging`; hash nguồn và staging phải giống nhau.
9. Không follow symlink/junction và không cho staging nằm trong source.
10. Không upload khi có collision; không auto-overwrite hoặc auto-rename. Dùng `scripts/sp_cnc_upload_ops.py check-collisions` trước upload và `scripts/sp_cnc_upload_ops.py upload-plan` để upload/patch metadata/verify; không tự viết lại Graph script tương tự trong workspace nếu helper đáp ứng yêu cầu.
11. Không cập nhật bất kỳ `CNC_MD_*` nào.
12. Không tạo folder ngoài config; nếu thiếu cây gói hoặc thiếu folder con theo template, phải preview danh sách sẽ tạo/bổ sung và chỉ gọi `cnc-create-package` sau khi user xác nhận rõ phần đó.
13. Metadata null phải để trống/xóa giá trị cũ; không dùng mã giả.
14. Sau upload phải xác minh filename, path, size/hash khi có và cả năm metadata.
15. Upload thành công nhưng metadata lỗi là `partial_failure`, không báo success.
16. Chỉ cleanup staging khi mọi file đã verified; giữ staging khi lỗi.
