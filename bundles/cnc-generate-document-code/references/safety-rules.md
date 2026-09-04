# Safety Rules

1. Master data là read-only.
2. Không gọi SharePoint write actions.
3. Không phát minh mã hoặc chọn ngẫu nhiên candidate.
4. Chỉ dùng bản ghi Active.
5. Thành phần không dùng trả `null`.
6. Không ghi `N/A`, `None`, `-` hoặc mã giả.
7. Không tạo DocumentCode khi thiếu trường bắt buộc.
8. Không sửa file, folder hoặc metadata.
9. Mỗi suy luận phải có evidence.
10. Không dùng `exampleCode`, `exampleFileName`, OCR example, cached formula/example hoặc tài liệu ví dụ để điền input thật còn thiếu. Ví dụ chỉ dùng để hiểu pattern; nếu thiếu field bắt buộc như `ParentContractCode`, `PhapNhan`, sequence hoặc ngày thì trả `needs_user_input` và hỏi user.
