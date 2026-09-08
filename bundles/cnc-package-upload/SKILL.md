---
name: cnc-package-upload
description: Phân loại, tạo mã, kiểm tra hoặc tạo package sau xác nhận, rồi stage/upload/verify hồ sơ CNC bằng một workflow hợp nhất.
---

# CNC Package Upload

Agent hiểu yêu cầu và nội dung hồ sơ, chọn documentTypeCode, xác định input mã và trình preview. Script thực hiện scan/hash file, snapshot/lookup master data, render mã, kiểm tra package, tạo package đã duyệt, stage, upload và verify.

Không load các skill CNC cũ và không đọc source Python trong quy trình thông thường. Chỉ đọc source khi helper lỗi hoặc user yêu cầu debug.

## Chỉ tạo mã

Khi user chỉ yêu cầu tạo mã và không yêu cầu upload/package, không chạy `prepare_upload.py`, không hỏi đường dẫn file, không kiểm tra package và không glob/grep matrix. Truyền trực tiếp tên nghiệp vụ hoặc code vào `document_code_engine.py --describe-type`; engine tự resolve business name/alias. Chỉ hỏi các trường trong `requiredForCode` của đúng rule còn thiếu bằng chứng; không biến metadata, filename, đơn vị phát hành, sequence hoặc revision thành yêu cầu chung cho mọi loại tài liệu.

Nếu tên nghiệp vụ đủ rõ và mọi `requiredForCode` đã có trong yêu cầu, gọi engine ngay. Nếu chưa resolve được duy nhất một loại tài liệu, hỏi đúng điểm phân loại còn mơ hồ trước; không hỏi một biểu mẫu trường cố định khi chưa biết rule.

Nếu script Graph trả token expired, gọi `iris_m365_refresh` rồi retry đúng command lỗi một lần. Không yêu cầu user đăng nhập lại trừ khi refresh tool thất bại.

## Chuẩn bị read-only

1. Chạy đúng một command để scan nguồn, refresh master data và preview package song song:

```bash
python scripts/prepare_upload.py inspect --source "<sourceFolderPath>" --package "<packageFolderName>" --workspace "<agentWorkingDirectory>" --output-dir ".cnc-work/<packageFolderName>"
```

2. Đọc JSON tóm tắt từ stdout hoặc `prepare-context.json`; không glob toàn skill, không đọc source script và không gọi `--help` trước.
3. Tra mọi mã master trong một command; `--kind` là alias của `--category`, nhưng ưu tiên `lookup-many` để tránh gọi lặp:

```bash
python scripts/master_data_snapshot.py lookup-many --snapshot "<masterSnapshotPath>" --query "projects=R02" --query "legalEntities=TTDN" --query "contractors=CTC" --query "documentTypes=IPC"
```
4. Agent phân loại file và ghi batch input dưới dạng `{"items":[...]}` vào workspace, không ghi trong thư mục skill. Engine cũng chấp nhận trực tiếp `[...]` để tránh lỗi envelope, nhưng luôn ưu tiên object có `items`.
5. Gọi `document_code_engine.py --input-file "<input>" --output "<codes>"` đúng một lần; không dùng shell redirect.
6. Build plan mà không tự đặt tên config routing:

```bash
python scripts/local_file_pipeline.py plan --scan "<scanPath>" --codes "<codesPath>" --package-folder "<packageFolderName>" --output "<workspace>/.cnc-work/<packageFolderName>/plan.json"
```

7. Kiểm tra collision và trình một preview duy nhất gồm filename, mã, metadata, destination và folder thiếu.

Preview chi tiết luôn là assistant message trong chat với bảng dễ đọc như nguồn, mã tài liệu, tên file mới, destination, metadata và collision. Chỉ sau khi message preview đã hiển thị mới gọi `ask_user_question`. Popup chỉ hỏi một câu ngắn nêu package và số file; không lặp bảng, đường dẫn dài, metadata hoặc danh sách folder trong câu hỏi. Trạng thái chờ hỏi sẽ để Desktop gửi notification cho user khi cửa sổ không focus.

`prepare_upload.py inspect` đã song song hóa các thao tác cơ học. Chỉ tạo subagent khi phân loại nhiều file cần đọc nội dung độc lập; không tạo subagent chỉ để scan hoặc kiểm tra package. Agent cha tự giao việc, hợp nhất theo relativePath, xử lý thiếu/trùng/mâu thuẫn và gom câu hỏi cho user trong một lượt.

## Sau xác nhận

Không tạo folder, stage hoặc upload trước khi user duyệt preview cụ thể. Sau khi duyệt:

Sau confirmation, chỉ chạy một command; không gọi riêng create/confirm/stage/collision/upload và không tự chọn config:

```bash
python scripts/execute_upload.py --package-plan "<packagePlanPath>" --upload-plan "<uploadPlanPath>" --workspace "<agentWorkingDirectory>" --output-dir ".cnc-work/<packageFolderName>/execute"
```

Script xác minh plan package, tạo và verify folder đã duyệt, confirm plan upload, stage bản copy, kiểm tra collision cuối, upload, gán metadata, đọc lại verify và chỉ cleanup khi toàn bộ thành công. Lỗi giữa chừng giữ output/checkpoint và staging để điều tra hoặc retry.

## Master data

Chỉ dùng item Status Active từ các List cấu hình. Snapshot phải ghi fetchedAt, site/list id và dữ liệu chuẩn hóa. Refresh lỗi không được thay snapshot tốt bằng dữ liệu rỗng. Lookup không có hoặc có nhiều candidate thì agent hỏi user; không tự đoán.

Agent vẫn chịu trách nhiệm hiểu ngữ nghĩa. Script không tự chọn loại hồ sơ, sequence, ngày, revision hoặc giá trị còn mơ hồ. Mọi mã cuối phải do document_code_engine.py render và validate.

## Cấm

- Không cập nhật các List CNC_MD_*.
- Không tạo package trước confirmation.
- Không upload trực tiếp từ source, overwrite hoặc auto-rename collision.
- Không báo success trước khi package, file và metadata được đọc lại xác minh.
