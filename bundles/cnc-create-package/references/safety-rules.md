# Safety Rules

1. Tên folder ngoài cùng lấy nguyên văn từ user, chỉ trim khoảng trắng đầu/cuối.
2. Không tự gắn mã, số thứ tự, tên gói hoặc hậu tố vào folder name.
3. Không đọc hoặc cập nhật `CNC_MD_*`.
4. Chỉ tạo trong site, library và packageRootPath của config.
5. Không tự sửa ký tự tên folder; nếu không hợp lệ phải hỏi user.
6. Không xóa, đổi tên hoặc di chuyển folder/file đã có.
7. Folder đã có thì chỉ bổ sung folder con thiếu theo template sau khi user đã xác nhận preview; khi được gọi từ `cnc-code-upload-file`, confirmation phải đến từ preview upload có nêu rõ các folder cần tạo/bổ sung. Preview chi tiết ở chat/file; popup confirmation chỉ hỏi ngắn gọn, không nhồi danh sách folder dài.
8. Không ghi đè xung đột.
9. Sau thao tác phải đọc lại toàn bộ cây để xác minh.
10. Dùng `scripts/sp_cnc_package_ops.py` cho preview/create/verify package tree; không tự viết lại script Graph tương tự trong workspace nếu helper đáp ứng yêu cầu.
