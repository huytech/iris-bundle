# Filename Normalization

## Mục tiêu

Tạo tên mới theo dạng:

`[DocumentCode]_[CleanOriginalBaseName].[extension]`

Giữ nguyên extension và phần mô tả hữu ích của tên file.

## Quyết định prefix cũ

1. Agent, không phải script, quyết định prefix cũ nào sẽ bỏ khỏi tên file.
2. Loại extension để lấy base name, rồi agent xem phần đầu tên file có phải prefix/mã cũ cần thay bằng `DocumentCode` mới hay không.
3. Agent chỉ chọn bỏ prefix khi đủ chắc dựa trên ngữ cảnh file, output tạo mã và quy tắc mã tài liệu; không dùng script regex/detect để tự quyết định.
4. Prefix cũ có thể chứa STT hoặc ngày ở cuối nếu agent xác định đó là một phần của mã/prefix cũ.
5. Xóa prefix và đúng một separator kế tiếp; phần còn lại ghi vào `cleanBaseName`.
6. Nếu không chắc chắn, giữ nguyên tên hoặc yêu cầu user xác nhận trong preview; không để script đoán thay.

Agent phải ghi quyết định vào `codes.json`:

```json
"fileNameDecision": {
  "status": "agent_decided",
  "oldPrefixToRemove": "M02_TDO_MEP02",
  "cleanBaseName": "Bao cao"
}
```

Nếu giữ nguyên toàn bộ stem tên cũ:

```json
"fileNameDecision": {
  "status": "keep_original",
  "oldPrefixToRemove": null,
  "cleanBaseName": "Bao_cao_tai_chinh_Coteccons"
}
```

## Ví dụ

- `M01_BID_MEP01_CTC_Bao cao tai chinh.pdf`
  - Prefix cũ: `M01_BID_MEP01_CTC`
  - Clean name: `Bao cao tai chinh`

- `Bao_cao_tai_chinh_Coteccons.pdf`
  - Không có prefix hợp lệ.
  - Không xóa token.

- `M02_TDO_MEP02_Ho so moi thau.xlsx` đổi sang `M01_TDO_MEP01`
  - Tên mới: `M01_TDO_MEP01_Ho so moi thau.xlsx`

## Chống lặp prefix

Nếu tên đã bắt đầu đúng `DocumentCode`, không gắn thêm lần nữa. Nếu bắt đầu bằng một mã hợp lệ khác, replace toàn bộ prefix cũ bằng mã mới.

## Làm sạch tối thiểu

- Bỏ `_` và khoảng trắng thừa ở ranh giới prefix/nội dung.
- Không tự dịch hoặc viết lại nội dung tên file.
- Không thay dấu tiếng Việt nếu user không yêu cầu.
- Không thay đổi extension.
