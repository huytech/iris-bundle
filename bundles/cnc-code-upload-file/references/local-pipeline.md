# Local File Pipeline

Script: `scripts/local_file_pipeline.py`

## Các lệnh

### Scan

```bash
python scripts/local_file_pipeline.py scan --source "D:\\CNC\\Source" --output scan.json
```

Đọc recursive mặc định, bỏ file tạm, không follow symlink, tính SHA-256.

### Plan

```bash
python scripts/local_file_pipeline.py plan --scan scan.json --codes codes.json --routing config/folder-routing.json --package-folder "1xx" --output plan.json
```

Lập filename/path/metadata và collision. Script không phát hiện prefix cũ; agent phải đưa quyết định prefix/clean base name trong `codes.json` tại `fileNameDecision` trước khi chạy plan. Chưa copy file.

### Confirm

Chỉ sau khi user duyệt preview:

```bash
python scripts/local_file_pipeline.py confirm --plan plan.json --output confirmed-plan.json
```

Nếu bất kỳ filename, destination hoặc metadata thay đổi sau đó, phải tạo plan mới và xác nhận lại.

### Stage

```bash
python scripts/local_file_pipeline.py stage --plan confirmed-plan.json --staging-root ".cnc-staging"
```

Copy bằng `copy2` vào `.partial`, kiểm hash rồi atomic rename. Không đổi tên/move file nguồn.

### Verify

```bash
python scripts/local_file_pipeline.py verify --manifest ".cnc-staging/<operationId>/manifest.json"
```

### Cleanup

Chỉ chạy sau khi mọi upload và metadata đã được đánh dấu verified:

```bash
python scripts/local_file_pipeline.py cleanup --manifest ".cnc-staging/<operationId>/manifest.json"
```

Nếu có lỗi/partial failure, giữ staging để retry.

## Upload boundary

Script chỉ xử lý local. Upload và gán metadata phải đi qua Microsoft 365 SharePoint tool. Agent phải cập nhật manifest/audit sau khi xác minh item đích.
