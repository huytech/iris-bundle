---
name: cnc-package-upload
description: Phân loại, tạo mã, kiểm tra hoặc tạo package sau xác nhận, rồi stage/upload/verify hồ sơ CNC bằng một workflow hợp nhất.
---

# CNC Package Upload

Agent hiểu yêu cầu và nội dung hồ sơ, đọc rule nghiệp vụ `HoSo` đã export, chọn documentTypeCode, xác định input mã và trình preview. Script thực hiện scan/hash file, snapshot/lookup master data, validate đề xuất, render mã, kiểm tra package, tạo package đã duyệt, stage, upload và verify.

Không đọc source Python trong quy trình thông thường. Chỉ đọc source khi helper lỗi hoặc user yêu cầu debug.

## CNC Auto Intake

Trong preset `CNC Agent`, khi user gửi file hoặc folder mà không gõ thêm nội dung, xem đó là yêu cầu CNC Auto Intake: tự đọc tên file, suy ra nghiệp vụ đủ rõ, đổi tên theo rule, chọn folder đích và lập preview upload. Không áp dụng hành vi này cho preset thường.

Không hỏi lại source khi file/folder đã nằm trong tin nhắn, attachment, file picker, workspace hoặc đường dẫn hội thoại đã nêu. Nếu user không gửi link SharePoint, vẫn tiếp tục bằng package/folder đích suy ra được từ tên file, folder nguồn hoặc ngữ cảnh phiên; chỉ hỏi khi không có đúng một package/folder đích có thể xác minh.

Khi chọn folder con, ưu tiên mã tài liệu đã render. Với mã thường, dùng token loại tài liệu 3 ký tự trong `DocumentCode`. Với nhóm hợp đồng, nếu mã chỉ có `CTR` thì vào folder `CTR`; nếu sau `CTR` có `IPC`, `VO`, `PL` hoặc `FAC` thì vào folder tương ứng. Không hỏi lại folder con khi route là duy nhất.

Khi gọi helper, `--document-type` chỉ nhận một mã nghiệp vụ atomic trong matrix như `FAC`, `IPC`, `VO`, `PL` hoặc `CTR`. Nếu tên file có chuỗi như `CTR_FAC`, `CTR_IPC`, `CTR_VO` hoặc `CTR_PL`, đó là ngữ cảnh hợp đồng cộng với loại hồ sơ con; truyền mã con (`FAC`, `IPC`, `VO`, `PL`) làm `--document-type`, không truyền mã ghép.

Nếu `prepare-and-plan` trả `ready`, `fileCount > 0`, `collisionCount = 0`, không có file unresolved và package plan chỉ tạo/bổ sung đúng cây folder template cho package đã suy ra, gửi preview trong chat rồi hỏi user duyệt giống quy trình upload thông thường. Không chạy `execute_upload.py` trước khi user xác nhận preview cụ thể. Auto Intake dừng lại và hỏi đúng một câu khi thiếu dữ kiện nghiệp vụ, có nhiều package/folder trùng, collision, source rỗng, unresolved file hoặc helper trả `invalid`/`blocked`.

## Chỉ tạo mã

Khi user chỉ yêu cầu tạo mã và không yêu cầu upload/package, không hỏi đường dẫn file và không kiểm tra package. Đọc `config/hoso-rules.semantic.json` cùng master data liên quan rồi dùng ngữ nghĩa trong hội thoại để lập proposal JSON như luồng preview. Chỉ mở `config/hoso-rules.json` khi cần trace về sheet gốc hoặc xử lý mâu thuẫn chưa rõ. Nếu proposal thiếu dữ liệu hoặc confidence thấp, hỏi đúng trường nghiệp vụ còn thiếu. Nếu proposal đủ dữ liệu, gọi `document_code_engine.py` bằng `documentTypeCode` và `values` trong proposal để render/validate mã cuối; không để mã LLM tự sinh thay thế renderer.

Chỉ hỏi các trường thật sự còn thiếu theo proposal và rule được chọn; không biến metadata, filename, đơn vị phát hành, sequence hoặc revision thành yêu cầu chung cho mọi loại tài liệu.

Nếu tên nghiệp vụ đủ rõ và mọi `requiredForCode` đã có trong yêu cầu, gọi engine ngay. Nếu chưa resolve được duy nhất một loại tài liệu, hỏi đúng điểm phân loại còn mơ hồ trước; không hỏi một biểu mẫu trường cố định khi chưa biết rule.

Nếu script Graph trả token expired, gọi `iris_m365_refresh` rồi retry đúng command lỗi một lần. Không yêu cầu user đăng nhập lại trừ khi refresh tool thất bại.

## Chuẩn bị và lập preview

Với yêu cầu upload, trước tiên đọc `config/hoso-rules.semantic.json`. Đây là bản semantic đã làm sạch từ sheet `HoSo`: một rule theo `documentTypeCode`, có business intent, khi nào chọn, alias, required fields, code pattern, ví dụ sạch và ambiguity notes. Chỉ mở `config/hoso-rules.json` khi cần đối chiếu nguồn sheet gốc. Dùng JSON semantic này cùng user request, tên file/nội dung file đã đọc và master data SharePoint để tự lập một proposal JSON có cấu trúc:

```json
{
  "selectedRuleRow": 12,
  "documentTypeCode": "BID",
  "confidence": 0.86,
  "values": {
    "DuAn": "M01",
    "GoiThau": "MEP01",
    "NhaThau": "CTC"
  },
  "proposedDocumentCode": "M01_BID_MEP01_CTC",
  "missingFields": [],
  "evidence": ["filename or content evidence", "HoSo row evidence"]
}
```

Nếu chưa đủ tự tin hoặc còn thiếu dữ liệu, đặt `missingFields` và `question` trong proposal; không tự bịa mã master. Proposal là cách agent phân loại bằng ngữ nghĩa từ rule `HoSo`; script vẫn là bước kiểm tra cuối để validate master, normalize sequence và render mã.

Với proposal đã có, chạy đúng một command. Command này scan nguồn, lấy master data có cache kiểm soát, kiểm tra package, validate proposal, dựng mã, lập plan và kiểm tra collision:

```bash
python scripts/prepare_upload.py prepare-and-plan --source "<sourceFolderPath>" --package "<packageFolderName>" --workspace "<agentWorkingDirectory>" --output-dir ".cnc-work/<packageFolderName>" --document-type auto --request-context "<conciseOriginalRequest>" --llm-proposal "<proposalJsonOrPath>"
```

`--source` là folder hoặc file nguồn agent đã truy cập được từ tin nhắn, attachment, file picker, workspace hoặc đường dẫn user đã nêu. Nếu user đã gửi folder/file hoặc đã có path trong hội thoại thì dùng path đó, không hỏi lại "đường dẫn folder nguồn". Thiếu link SharePoint/folder đích không đồng nghĩa thiếu source; khi thiếu link đích, tự lập preview bằng package/folder đích đã suy ra hoặc hỏi đúng package/folder đích, không hỏi source. Chỉ hỏi source một lần khi trong hội thoại thật sự chưa có folder/file/path nào agent có thể scan.

Agent phân loại nghiệp vụ và tổng hợp dữ liệu từ toàn bộ hội thoại hiện tại, `hoso-rules.semantic.json`, tên file và nội dung hồ sơ đã đọc. Không hỏi lại dữ liệu đã xuất hiện. Script tự chuẩn hóa sequence, resolve code/name theo master và tự dựng mã hợp đồng cha khi đủ thành phần. `--value "<knownBusinessField>=<value>"` vẫn dùng được như override thủ công khi user vừa bổ sung một field sau câu hỏi.

Các tên field ưu tiên khi truyền `--value` là `DuAn`, `GoiThau`, `PhapNhan`, `NhaThau`, `ContractSequence`, `DocumentSequence`, `ParentContractCode` và `ExpiryDateYYMMDD`. `ContractSequence` và `DocumentSequence` bắt buộc là số từ 1 đến 99, có thể có số 0 ở đầu. Khi user nói `đợt 1`, `lần thứ 2` hoặc `kỳ 03`, truyền lần lượt `DocumentSequence=1`, `DocumentSequence=2` hoặc `DocumentSequence=03`; không truyền nguyên cụm nghiệp vụ vào `--value`. Giữ câu gốc trong `--request-context` để helper có thể kiểm tra và tự chuẩn hóa. Script chấp nhận các alias tiếng Anh thông dụng nhưng agent phải giữ nguyên dữ kiện rõ ràng trong lời user và không hỏi lại dữ kiện đã xác định duy nhất.

Ví dụ đúng: `--request-context "Hồ sơ thanh toán đợt 1" --value "DocumentSequence=1"`. Ví dụ sai: `--value "DocumentSequence=đợt 1"`.

`--package` là tên package/folder đích do user cung cấp. Giá trị này chỉ dùng để xác định nơi upload, không phải metadata và không phải thành phần mã. Không sao chép, suy diễn hoặc chuẩn hóa nó thành `GoiThau`. Chỉ truyền `GoiThau` khi đúng rule mã yêu cầu gói thầu nghiệp vụ và dữ kiện đó có bằng chứng riêng. Nếu agent lặp lại package đích trong `--value`, dùng `DestinationPackage`; script chỉ chấp nhận khi trùng `--package`. Script bỏ qua field không được rule hiện tại sử dụng để field thừa không tạo câu hỏi sai.

Folder con upload được suy ra từ mã tài liệu đã render, không hỏi user lại khi route duy nhất trong template. Với mã thường, dùng document type token trong `DocumentCode` như `PTE`, `BID`, `TDO`. Với nhóm hợp đồng, nếu mã chỉ có `CTR` thì vào folder `CTR`; nếu sau `CTR` có `IPC`, `VO`, `PL` hoặc `FAC` thì route theo token đó. Không route theo filename gốc khi `DocumentCode` đã có, vì filename có thể chứa prefix cũ. Chỉ hỏi user khi không xác định được package/folder đích hoặc có nhiều package/folder trùng khớp.

Nếu `status=needs_user_input`, dùng `question` do script trả về và chỉ hỏi một lần. Sau câu trả lời, gọi `plan-batch` đúng một lần với `contextPath` đã có; không chạy lại scan. Nếu `status=invalid`, báo dữ liệu nào không hợp lệ từ `errors`, không mô tả là thiếu dữ liệu và không hỏi duyệt upload. Nếu `status=blocked`, báo collision và không hỏi duyệt upload. Nếu `status=ready`, phản hồi hiện tại chỉ được gửi preview dạng Markdown table trong chat kèm một câu ngắn rằng sẽ hỏi duyệt sau khi user xem xong; dừng lượt tại đó và không gọi tool hỏi xác nhận trong cùng response.

Không xin xác nhận nếu `fileCount=0`, `unresolvedFileCount>0`, preview thiếu file hoặc status khác `ready`. Số dòng dữ liệu trong preview phải bằng số file nguồn hợp lệ đã scan.

Preview chi tiết luôn là assistant message trong chat, không phải popup. Message preview phải có Markdown table cơ bản để user thấy và review ngay, tối thiểu gồm: tên file nguồn, mã tài liệu, tên file sau upload, SharePoint path đích và collision. Không show path nguồn local/cache/workspace như `.cnc-auto-intake`, `%APPDATA%`, `C:\Users\...` hoặc đường dẫn file nội bộ trong message cho user; các path này chỉ dùng nội bộ để chạy helper. Có thể thêm metadata quan trọng dưới bảng bằng vài dòng ngắn, nhưng không giấu thông tin review trong popup. Không được đặt preview table và `ask_user_question` trong cùng một assistant response, vì Desktop có thể hiển thị popup trước khi user thấy message. Chỉ ở lượt sau, khi preview đã nằm trong timeline chat hoặc user nói đã xem/duyệt/tiếp tục, mới gọi `ask_user_question`. Popup chỉ hỏi một câu ngắn nêu package và số file; không lặp bảng, đường dẫn dài, metadata hoặc danh sách folder trong câu hỏi. Trạng thái chờ hỏi sẽ để Desktop gửi notification cho user khi cửa sổ không focus.

Không đưa source path nội bộ vào `--request-context`, proposal `evidence`, preview message hoặc câu hỏi xác nhận. `--request-context` chỉ chứa nghiệp vụ user nói, ví dụ loại hồ sơ, dự án, nhà thầu, ngày, hợp đồng hoặc package đích. Source path chỉ truyền qua tham số `--source`.

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
