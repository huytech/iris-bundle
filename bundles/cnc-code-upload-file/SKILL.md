---
name: cnc-code-upload-file
description: Quét folder local, lập preview bắt buộc, copy/rename vào staging bằng script, rồi upload SharePoint và gán năm metadata; không sửa nguồn hay tự tạo mã.
---

# CNC Code and Upload File

## Mục đích

Xử lý file từ một folder local do user truyền vào. Skill lập kế hoạch, bắt buộc user duyệt filename/location/metadata, tạo bản copy đã đổi tên trong staging bằng Python, sau đó mới upload SharePoint.

Không rename/move/xóa file nguồn. Không tự phân loại hoặc tạo mã.

## Đọc trước khi xử lý

1. `config/sharepoint.json`
2. `config/folder-routing.json`
3. `references/safety-rules.md`

Chỉ đọc reference khi đến bước cần nó: `references/filename-normalization.md` lúc quyết định filename, `references/metadata-mapping.md` lúc lập plan metadata, và `references/local-pipeline.md` trước stage/cleanup. Không nạp tất cả reference vào context từ đầu.

Nếu SharePoint `libraryName` hoặc `destinationRootPath` còn `__REQUIRED__`, hỏi user; không tự đoán.

## Input

Tối thiểu:

```json
{
  "sourceFolderPath": "D:\\CNC\\Source",
  "packageFolderName": "1xx"
}
```

- `sourceFolderPath`: folder local do user chỉ định.
- `packageFolderName`: tên folder gói trên SharePoint, lấy nguyên văn từ user.
- Mặc định quét recursive, không follow symlink/junction và loại file tạm theo config.

## Dependency

- `cnc-generate-document-code`: phân loại và tạo mã bằng Python engine.
- `cnc-create-package`: tạo cây folder gói nếu thiếu; skill này có helper `scripts/sp_cnc_package_ops.py` để preview/create/verify package tree, không cần agent tự viết Graph script.
- `scripts/local_file_pipeline.py`: scan, plan, confirm, stage, verify và cleanup local.
- `scripts/sp_cnc_upload_ops.py`: helper SharePoint chính thức cho check collision, upload từ staging, patch metadata và verify; không cần agent tự viết Graph script.

Chỉ xử lý output mã có `status = ready`.

## Quy trình bắt buộc

### 1. Scan local source

Chạy:

```bash
python scripts/local_file_pipeline.py scan --source "<sourceFolderPath>" --output scan.json
```

Ghi nhận relative path, size, modified time và SHA-256. Không sửa nguồn.

### 2. Phân loại và tạo mã theo batch

Load `cnc-generate-document-code` một lần cho toàn bộ batch. Phân loại tất cả file trong một lượt, đọc master data Active một lần, rồi tạo một `code-input.json` chứa `items[]`; mỗi item dùng `relativePath` làm `id`. Gọi engine một lần:

```bash
python ../cnc-generate-document-code/scripts/document_code_engine.py --input-file code-input.json > codes.json
```

Kết quả batch có `results` keyed theo `relativePath`; `local_file_pipeline.py plan` đọc trực tiếp envelope này. Gom mọi câu hỏi thiếu/mơ hồ trong một bảng cho toàn batch. Không gọi lại skill/engine riêng từng file và không tự sửa output của engine.

### 3. Resolve destination

- Resolve site/library từ config.
- Dùng `packageFolderName` của user.
- Tra `LoaiTaiLieu` trong `folder-routing.json` để lấy folder con demo.
- Kiểm tra `{destinationRootPath}/{packageFolderName}` trên SharePoint.
- Nếu cây gói chưa có hoặc thiếu folder con theo template, phải đưa vào preview upload phần “cây folder cần tạo/bổ sung” và hỏi user xác nhận rõ việc tạo/bổ sung bằng `cnc-create-package` trước khi upload.
- Nếu user xác nhận preview upload bao gồm rõ danh sách folder cần tạo/bổ sung, được gọi `cnc-create-package`; không tạo package âm thầm.
- Sau khi `cnc-create-package` chạy xong, đọc lại/xác minh package tree rồi mới kiểm tra file trùng tên trên SharePoint bằng `scripts/sp_cnc_upload_ops.py check-collisions` trước confirmation upload cuối cùng.

### 4. Build plan, chưa copy

Chạy:

```bash
python scripts/local_file_pipeline.py plan --scan scan.json --codes codes.json --routing config/folder-routing.json --package-folder "<packageFolderName>" --output plan.json
```

Agent quyết định prefix cũ sẽ bỏ trước khi gọi `plan` và ghi quyết định vào `codes.json` tại `fileNameDecision`. Script không tự detect prefix cũ; script chỉ áp dụng quyết định agent đã đưa, tạo filename dự kiến và kiểm collision trong batch.

Schema tối thiểu cho từng file ready trong `codes.json`:

```json
"relative/path.pdf": {
  "status": "ready",
  "DocumentCode": "M01_TDO_MEP01",
  "components": { "DuAn": "M01", "LoaiTaiLieu": "TDO", "GoiThau": "MEP01", "PhapNhan": null, "NhaThau": null },
  "fileNameDecision": {
    "status": "agent_decided",
    "oldPrefixToRemove": "M02_TDO_MEP02",
    "cleanBaseName": "Bao cao"
  }
}
```

Nếu agent không chắc prefix nào cần bỏ, đặt file đó `needs_user_input` hoặc `fileNameDecision.status = "needs_user_input"`; không để script đoán thay.

### 5. Preview bắt buộc

Preview chi tiết phải được gửi trong nội dung chat chính, KHÔNG nhồi bảng dài vào popup hỏi xác nhận.

Luôn hiển thị trước khi ghi trong chat chính:

| File local | Prefix cũ sẽ bỏ | DocumentCode | Tên file mới | DuAn | LoaiTaiLieu | GoiThau | PhapNhan | NhaThau | SharePoint path | Collision |
|---|---|---|---|---|---|---|---|---|---|---|

Kèm tổng số file, file ready, cần input, unsupported, tổng dung lượng và cây folder cần tạo/bổ sung. Nếu package folder chưa tồn tại hoặc thiếu template folders, preview phải nêu rõ sẽ gọi `cnc-create-package` sau khi user duyệt phần tạo/bổ sung package.

Nếu preview dài, vẫn ưu tiên cho user review ngay trong chat:

1. Chat chính: tóm tắt dễ đọc + bảng preview đầy đủ cho toàn bộ file cần upload.
2. File preview `.md`/`.json`: lưu thêm full plan/preview để audit hoặc mở riêng khi bảng quá dài.
3. Popup confirmation: chỉ hỏi 1 câu ngắn, có tham chiếu số lượng file/package và file preview, không chứa markdown table dài.

Nếu số file quá lớn khiến chat bị quá tải, chat chính phải hiển thị bảng đầy đủ theo từng chunk liên tiếp hoặc nêu rõ đã lưu file preview đầy đủ; không được thay popup/modal thành nơi review chính.

Mẫu popup đúng:

```text
Anh duyệt preview upload TTG.001 không? Sẽ tạo package TTG.001 nếu thiếu, stage/upload 2 file, gán metadata M01/INV/MEP01. Chi tiết ở cnc-preview-TTG.001.md.
```

### 6. Confirmation bắt buộc

Phải hỏi user xác nhận preview cụ thể bằng câu ngắn, dễ duyệt. Yêu cầu chung như “xử lý”, “rename” hoặc “upload” không được xem là đã duyệt tên và location.

Nếu filename, metadata hoặc destination thay đổi, confirmation cũ vô hiệu và phải preview lại.

Sau khi user xác nhận, chuyển plan sang confirmed:

```bash
python scripts/local_file_pipeline.py confirm --plan plan.json --output confirmed-plan.json
```

### 7. Stage copy

Chạy:

```bash
python scripts/local_file_pipeline.py stage --plan confirmed-plan.json --staging-root ".cnc-staging"
```

Script:

- Kiểm tra source chưa thay đổi từ lúc scan.
- Copy nguồn vào file `.partial`.
- So sánh SHA-256.
- Atomic rename bản staging thành filename mới.
- Không rename/move file nguồn.
- Viết manifest trong `.cnc-staging/<operationId>/manifest.json`.

### 8. Upload SharePoint

Trước upload sau khi stage, chạy kiểm tra collision đích:

```bash
python scripts/sp_cnc_upload_ops.py check-collisions --config config/sharepoint.json --plan staged-plan.json --output collisions.json
```

Nếu có collision, dừng và hỏi user; không upload.

Upload từ `stagingPath`, không upload trực tiếp từ file nguồn. Không thay filename/location sau confirmation. Không overwrite hoặc auto-rename collision.

Dùng helper chính thức để upload, patch metadata và verify thay vì tự viết Graph script:

```bash
python scripts/sp_cnc_upload_ops.py upload-plan --config config/sharepoint.json --plan staged-plan.json --output uploaded-plan.json --summary-output upload-summary.json
```

Helper trả `uploaded-plan.json` đã cập nhật `sharePointUrl`, `sharePointItemId`, `verifiedMetadata`, `verifiedSize`, `uploadState` và `state`.

### 9. Gán metadata

Gán đúng năm cột text từ output code engine:

- `DuAn`
- `LoaiTaiLieu`
- `GoiThau`
- `PhapNhan`
- `NhaThau`

Giá trị null phải để trống/xóa metadata cũ.

### 10. Verify

Đọc lại item đích và kiểm tra:

- File tồn tại đúng path.
- Filename đúng plan.
- Size và hash khi Graph cung cấp.
- Năm metadata khớp.
- Source local vẫn tồn tại và không thay đổi.

Upload thành công nhưng metadata lỗi phải báo `partial_failure` và giữ staging để retry.

### 11. Cleanup

Chỉ sau khi tất cả file được xác minh `verified`:

```bash
python scripts/local_file_pipeline.py cleanup --manifest ".cnc-staging/<operationId>/manifest.json"
```

Nếu có lỗi, không cleanup.

## Trạng thái

`discovered → code_ready → planned → awaiting_confirmation → confirmed → staged → uploaded → metadata_applied → verified → success`

Lỗi giữa chừng: `needs_user_input`, `unsupported`, `blocked`, `partial_failure`, `failed`.

## Cấm

- Không cập nhật `CNC_MD_*`.
- Không tự phân loại/tạo/sửa DocumentCode.
- Không rename/move/xóa source.
- Không stage trước confirmation.
- Không upload trực tiếp từ source.
- Không ghi đè hoặc tự thêm hậu tố chống trùng.
- Không tạo folder ngoài config.
- Không báo success trước khi file và metadata được đọc lại, xác minh.
