# Classification Policy

## Nguyên tắc

- Phân loại dựa trên bằng chứng, không chỉ từ một từ khóa đơn lẻ.
- Yêu cầu rõ của user có ưu tiên cao nhất nhưng phải khớp master.
- Alias chỉ tạo candidate, không tự động bảo đảm kết quả.
- Folder/path là ngữ cảnh hỗ trợ, không thay bằng chứng nội dung.
- Ví dụ trong matrix/workbook/OCR chỉ dùng để hiểu pattern, không phải evidence để fill input thật còn thiếu.

## Confidence

- `1.00`: user chỉ định mã rõ và khớp master.
- `0.90-0.99`: prefix/metadata hợp lệ và nội dung nhất quán.
- `0.80-0.89`: tên file có cụm từ đặc trưng duy nhất và khớp master.
- `<0.80`: không đủ để tự hoàn tất; đặt `needs_user_input`.

## Xử lý xung đột

- User khác metadata: hỏi xác nhận thay đổi.
- Metadata khác prefix: không chọn tự động.
- Tên file cho nhiều loại tài liệu: trả candidates trong `ambiguousFields`.
- Một mã master có nhiều tên: đưa dùng cả mã và tên để user chọn; không tự chọn.

## Evidence

Mỗi trường được suy ra phải có evidence ngắn, ví dụ:

- `User supplied: M01`
- `Existing valid prefix: BID`
- `Filename contains: hồ sơ dự thầu`
- `OCR heading: BẢNG KHỐI LƯỢNG`
