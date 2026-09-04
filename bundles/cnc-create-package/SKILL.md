---
name: cnc-create-package
description: Tạo hoặc bổ sung nguyên cây thư mục gói thầu demo trên SharePoint, với tên folder ngoài cùng lấy nguyên văn từ user; không đọc hay cập nhật master data.
---

# CNC Create Package Folder

## Mục đích

Tạo một folder gói thầu trên SharePoint và nguyên cây thư mục con theo template demo đã được xác nhận.

Tên folder ngoài cùng do user cung cấp nguyên văn. Skill không tự ghép mã dự án, mã gói, số thứ tự hoặc hậu tố.

Ví dụ user nhập `1xx` thì folder ngoài cùng là đúng `1xx`.

## Đọc trước khi làm

1. `config/sharepoint.json`
2. `config/package-folder-template.json`
3. `references/safety-rules.md`

Nếu `libraryName` hoặc `packageRootPath` còn `__REQUIRED__`, phải hỏi user; không tự chọn library/path.

## Input bắt buộc

```json
{
  "packageFolderName": "1xx"
}
```

- `packageFolderName` là tên folder, không phải mã dữ liệu.
- Giữ nguyên nội dung user nhập sau khi trim khoảng trắng đầu/cuối.
- Không tra hoặc cập nhật `CNC_MD_Packages` để quyết định tên folder.

## Validate tên folder

Từ chối hoặc yêu cầu user sửa nếu tên:

- Rỗng hoặc chỉ có khoảng trắng.
- Chứa ký tự SharePoint không hợp lệ: `" * : < > ? / \\ |`.
- Kết thúc bằng dấu chấm hoặc khoảng trắng.
- Là tên hệ thống bị cấm theo config.

Không tự thay ký tự hoặc tự chuẩn hóa tên mà chưa hỏi user.

## Script hỗ trợ

Dùng script có sẵn thay vì tự viết ad-hoc Graph code:

```bash
python scripts/sp_cnc_package_ops.py preview --config config/sharepoint.json --template config/package-folder-template.json --package "<packageFolderName>" --output package-preview.json
python scripts/sp_cnc_package_ops.py create  --config config/sharepoint.json --template config/package-folder-template.json --package "<packageFolderName>" --output package-create-result.json
```

Script xử lý:

- Resolve site/library từ config.
- Validate tên package theo config.
- Preview folder đã có/còn thiếu bằng Graph batch read, tối đa 20 path mỗi request.
- Tạo folder cha trước, con sau với conflictBehavior `fail`.
- Đọc lại toàn bộ cây để verify.

Không tự tạo lại script tương tự trong workspace nếu script này đáp ứng được yêu cầu.

## Quy trình

1. Đọc config và template.
2. Chạy `sp_cnc_package_ops.py preview` để resolve site/library và kiểm tra cây folder.
3. Hiển thị preview trong chat/file; popup confirmation nếu có chỉ hỏi ngắn.
4. Nếu được phép tạo/bổ sung, chạy `sp_cnc_package_ops.py create`.
5. Nếu đã có, không đổi tên và không tạo folder trùng.
6. Script so sánh cây thực tế với toàn bộ `folders[].path` trong template và tạo folder con còn thiếu theo thứ tự cha trước, con sau.
7. Không xóa hoặc đổi tên thành phần đang có nhưng khác template; báo để user xử lý.
8. Đọc kết quả script và xác minh `verified = true`. Nếu không verified, báo lỗi và không coi là hoàn tất.

## Preview

Vì template có nhiều folder, trước khi ghi phải hiển thị trong chat chính hoặc file preview, không nhồi toàn bộ danh sách folder vào popup confirmation:

- Site và library.
- Package root path.
- Tên folder user nhập.
- Số folder sẽ tạo mới.
- Folder đã tồn tại và folder còn thiếu.

Popup confirmation, nếu dùng, chỉ hỏi ngắn gọn. Ví dụ:

```text
Anh duyệt tạo/bổ sung package TTG.001 trong AIT DATA/90 TENDER DEMO không? Chi tiết folder trong preview ở chat/file.
```

Nếu được gọi độc lập và user đã yêu cầu rõ “tạo”, “thực hiện”, “triển khai” thì được thực thi ngay sau khi validate.

Nếu được gọi từ `cnc-code-upload-file` vì package chưa có hoặc thiếu folder con, chỉ thực thi khi preview upload đã nêu rõ danh sách folder cần tạo/bổ sung và user đã xác nhận phần tạo/bổ sung package. Không tạo package âm thầm chỉ vì đang chuẩn bị upload.

## Cấm

- Không đọc, tạo, sửa hoặc xóa bất kỳ `CNC_MD_*` nào.
- Không tự tạo mã gói thầu.
- Không đưa mã vào tên folder nếu user không nhập.
- Không tạo ngoài root path.
- Không xóa, move hoặc rename folder/file hiện có.

## Kết quả

- `packageFolderName`.
- Đường dẫn SharePoint đầy đủ.
- Folder đã có.
- Folder đã tạo.
- Folder khác template/cần kiểm tra.
- Trạng thái xác minh.
