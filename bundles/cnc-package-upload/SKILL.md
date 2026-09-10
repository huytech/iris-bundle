---
name: cnc-package-upload
description: Phân loại, tạo mã, kiểm tra hoặc tạo package sau xác nhận, rồi stage/upload/verify hồ sơ CNC bằng một workflow hợp nhất.
---

# CNC Package Upload

Agent hiểu yêu cầu và nội dung hồ sơ, chọn documentTypeCode, xác định input mã và trình preview. Script thực hiện scan/hash file, snapshot/lookup master data, render mã, kiểm tra package, tạo package đã duyệt, stage, upload và verify.

Không đọc source Python trong quy trình thông thường. Chỉ đọc source khi helper lỗi hoặc user yêu cầu debug.

## Chỉ tạo mã

Khi user chỉ yêu cầu tạo mã và không yêu cầu upload/package, không chạy `prepare_upload.py`, không hỏi đường dẫn file, không kiểm tra package và không glob/grep matrix. Truyền trực tiếp tên nghiệp vụ hoặc code vào `document_code_engine.py --describe-type`; engine tự resolve business name/alias. Chỉ hỏi các trường trong `requiredForCode` của đúng rule còn thiếu bằng chứng; không biến metadata, filename, đơn vị phát hành, sequence hoặc revision thành yêu cầu chung cho mọi loại tài liệu.

Nếu tên nghiệp vụ đủ rõ và mọi `requiredForCode` đã có trong yêu cầu, gọi engine ngay. Nếu chưa resolve được duy nhất một loại tài liệu, hỏi đúng điểm phân loại còn mơ hồ trước; không hỏi một biểu mẫu trường cố định khi chưa biết rule.

Nếu script Graph trả token expired, gọi `iris_m365_refresh` rồi retry đúng command lỗi một lần. Không yêu cầu user đăng nhập lại trừ khi refresh tool thất bại.

## Chuẩn bị và lập preview

Với yêu cầu upload đã có đủ dữ kiện nghiệp vụ, chạy đúng một command. Command này scan nguồn, lấy master data có cache kiểm soát, kiểm tra package, dựng mã, validate master, lập plan và kiểm tra collision:

```bash
python scripts/prepare_upload.py prepare-and-plan --source "<sourceFolderPath>" --package "<packageFolderName>" --workspace "<agentWorkingDirectory>" --output-dir ".cnc-work/<packageFolderName>" --document-type "<businessNameOrCode>" --request-context "<conciseOriginalRequest>" --value "<knownBusinessField>=<value>"
```

Agent phân loại nghiệp vụ và tổng hợp dữ liệu từ toàn bộ hội thoại hiện tại, tên file và nội dung hồ sơ đã đọc. Không hỏi lại dữ liệu đã xuất hiện. Script tự chuẩn hóa sequence, resolve code/name theo master và tự dựng mã hợp đồng cha khi đủ thành phần.

Các tên field ưu tiên khi truyền `--value` là `DuAn`, `GoiThau`, `PhapNhan`, `NhaThau`, `ContractSequence`, `DocumentSequence`, `ParentContractCode` và `ExpiryDateYYMMDD`. `ContractSequence` và `DocumentSequence` bắt buộc là số từ 1 đến 99, có thể có số 0 ở đầu. Khi user nói `đợt 1`, `lần thứ 2` hoặc `kỳ 03`, truyền lần lượt `DocumentSequence=1`, `DocumentSequence=2` hoặc `DocumentSequence=03`; không truyền nguyên cụm nghiệp vụ vào `--value`. Giữ câu gốc trong `--request-context` để helper có thể kiểm tra và tự chuẩn hóa. Script chấp nhận các alias tiếng Anh thông dụng nhưng agent phải giữ nguyên dữ kiện rõ ràng trong lời user và không hỏi lại dữ kiện đã xác định duy nhất.

Ví dụ đúng: `--request-context "Hồ sơ thanh toán đợt 1" --value "DocumentSequence=1"`. Ví dụ sai: `--value "DocumentSequence=đợt 1"`.

`--package` là tên package/folder đích do user cung cấp. Giá trị này chỉ dùng để xác định nơi upload, không phải metadata và không phải thành phần mã. Không sao chép, suy diễn hoặc chuẩn hóa nó thành `GoiThau`. Chỉ truyền `GoiThau` khi đúng rule mã yêu cầu gói thầu nghiệp vụ và dữ kiện đó có bằng chứng riêng. Nếu agent lặp lại package đích trong `--value`, dùng `DestinationPackage`; script chỉ chấp nhận khi trùng `--package`. Script bỏ qua field không được rule hiện tại sử dụng để field thừa không tạo câu hỏi sai.

Nếu `status=needs_user_input`, dùng `question` do script trả về và chỉ hỏi một lần. Sau câu trả lời, gọi `plan-batch` đúng một lần với `contextPath` đã có; không chạy lại scan. Nếu `status=invalid`, báo dữ liệu nào không hợp lệ từ `errors`, không mô tả là thiếu dữ liệu và không hỏi duyệt upload. Nếu `status=blocked`, báo collision và không hỏi duyệt upload. Nếu `status=ready`, gửi nguyên `previewMarkdown` trong chat rồi mới hỏi xác nhận bằng một câu ngắn.

Không xin xác nhận nếu `fileCount=0`, `unresolvedFileCount>0`, preview thiếu file hoặc status khác `ready`. Số dòng dữ liệu trong preview phải bằng số file nguồn hợp lệ đã scan.

Preview chi tiết luôn là assistant message trong chat với bảng dễ đọc như nguồn, mã tài liệu, tên file mới, destination, metadata và collision. Chỉ sau khi message preview đã hiển thị mới gọi `ask_user_question`. Popup chỉ hỏi một câu ngắn nêu package và số file; không lặp bảng, đường dẫn dài, metadata hoặc danh sách folder trong câu hỏi. Trạng thái chờ hỏi sẽ để Desktop gửi notification cho user khi cửa sổ không focus.

Không dùng `todo_write` cho workflow này. Không đọc lại context, snapshot, matrix hoặc output JSON khi stdout đã có status, question hoặc preview. Không gọi `--describe-type` trong luồng upload. Không gọi lại `prepare-and-plan` để dò input. Chỉ tạo subagent khi nhiều file cần đọc nội dung độc lập; không tạo subagent để scan, tra master, render mã, build plan hoặc kiểm tra package/collision.

## Sau xác nhận

Không tạo folder, stage hoặc upload trước khi user duyệt preview cụ thể. Sau khi duyệt:

Sau confirmation, chỉ chạy một command; không gọi riêng create/confirm/stage/collision/upload và không tự chọn config:

```bash
python scripts/execute_upload.py --package-plan "<packagePlanPath>" --upload-plan "<uploadPlanPath>" --workspace "<agentWorkingDirectory>" --output-dir ".cnc-work/<packageFolderName>/execute"
```

Script xác minh plan package, tạo và verify folder đã duyệt, confirm plan upload, stage bản copy, kiểm tra collision cuối, upload, gán metadata, đọc lại verify và chỉ cleanup khi toàn bộ thành công. Lỗi giữa chừng giữ output/checkpoint và staging để điều tra hoặc retry.

## Master data

Chỉ dùng item Status Active từ các List cấu hình. Snapshot phải ghi fetchedAt, site/list id và dữ liệu chuẩn hóa. Refresh lỗi không được thay snapshot tốt bằng dữ liệu rỗng. Lookup không có hoặc có nhiều candidate thì agent hỏi user; không tự đoán.

Master snapshot chỉ được cache tối đa 5 phút. Cache thiếu cấu trúc, sai timestamp hoặc hết hạn phải refresh. Giá trị agent cung cấp và các segment trong mã hợp đồng cha đều phải resolve duy nhất với master trước khi tạo mã. Collision và upload không dùng cache.

Agent chịu trách nhiệm hiểu ngữ nghĩa và tái sử dụng dữ liệu trong session. Cụm chỉ thứ tự đợt/lần/kỳ rõ ràng được truyền trong `--request-context` để script chuẩn hóa thành sequence. Với hồ sơ con của hợp đồng, truyền các thành phần nghiệp vụ đã biết; script tự dựng mã hợp đồng cha khi đủ dữ liệu. Script không tự chọn loại hồ sơ, ngày, revision hoặc giải quyết trường hợp có nhiều cách hiểu. Mọi mã cuối phải do document_code_engine.py render và validate.

Không hỏi user bằng tên biến như `ParentContractCode`, `DocumentSequence` hoặc `ContractSequence`. Nếu thiếu dữ liệu, hỏi đúng khái niệm nghiệp vụ tương ứng. Không yêu cầu user cung cấp nguyên mã hợp đồng khi dự án, pháp nhân, nhà thầu và số thứ tự hợp đồng đã xác định được.

## Cấm

- Không cập nhật các List CNC_MD_*.
- Không tạo package trước confirmation.
- Không upload trực tiếp từ source, overwrite hoặc auto-rename collision.
- Không báo success trước khi package, file và metadata được đọc lại xác minh.
