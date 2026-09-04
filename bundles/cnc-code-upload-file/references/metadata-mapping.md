# Metadata Mapping

Document library lưu năm cột kiểu text:

| Output component | SharePoint column |
|---|---|
| DuAn | DuAn |
| LoaiTaiLieu | LoaiTaiLieu |
| GoiThau | GoiThau |
| PhapNhan | PhapNhan |
| NhaThau | NhaThau |

## Quy tắc

- Ghi đúng mã chuẩn từ output `cnc-generate-document-code`.
- Không ghi tên diễn giải.
- Thành phần `null` phải để trống cột.
- Khi replace file/metadata cũ, phải xóa giá trị cột cũ nếu output mới là `null`.
- Không dùng `N/A`, `None`, `-`, chuỗi `null` hoặc mã giả.
- Sau ghi phải đọc lại cả năm cột.
