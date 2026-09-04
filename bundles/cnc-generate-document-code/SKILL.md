---
name: cnc-generate-document-code
description: Phân loại hồ sơ CNC, đọc master data read-only và gọi Python engine tất định để tạo mã cùng năm metadata; không sửa file hay ghi SharePoint.
---

# CNC Generate Document Code

## Mục đích

Phân loại hồ sơ, thu thập đúng input và dùng engine Python tất định để tạo mã. LLM không tự nối chuỗi mã.

Skill không đổi tên, upload/copy, tạo folder hoặc cập nhật master data.

## Đọc trước khi xử lý

1. `config/document-code-matrix.json` — nguồn quy tắc runtime cao nhất, biên soạn từ toàn bộ cột/note/ví dụ sheet `HoSo`.
2. `config/master-data.json`
3. `config/classification-aliases.json`
4. `references/classification-policy.md`
5. `references/output-schema.md`
6. `references/safety-rules.md`
7. `references/document-code-rules.md` — bản đọc nhanh; matrix luôn thắng khi khác.
8. Iris Wiki chỉ để giải thích; không được ghi đè matrix hoặc master data.

## Nguồn dữ liệu

Master data runtime, read-only:

- `CNC_MD_Projects`
- `CNC_MD_PackageGroups`
- `CNC_MD_Packages`
- `CNC_MD_DocumentTypes`
- `CNC_MD_Contractors`
- `CNC_MD_LegalEntities`

Chỉ dùng bản ghi `Status = Active`.

## Ba lớp dữ liệu phải phân biệt

1. `requiredForCode`: input tối thiểu trực tiếp để render mã.
2. `ParentContractCode`: mã cha đã cấp; nếu hợp lệ thì không hỏi lại các segment bên trong.
3. Năm metadata file: `DuAn`, `LoaiTaiLieu`, `GoiThau`, `PhapNhan`, `NhaThau`; parse/derive từ mã cuối hoặc input tùy `metadataPolicy`. Thành phần không có để `null` và không chặn tạo mã.

Ví dụ FAC chỉ cần:

```json
{"documentTypeCode":"FAC","values":{"ParentContractCode":"R02_TTDN_CTC_CTR_01"}}
```

Kết quả phải là `R02_TTDN_CTC_CTR_01_FAC`; không hỏi `GoiThau`.

## Thứ tự bằng chứng phân loại

1. Chỉ định rõ của user.
2. Metadata hiện có.
3. Prefix mã cũ hợp lệ.
4. Tên file và folder.
5. Nội dung/OCR.
6. Alias phân loại.

Thông tin user vẫn phải khớp master data.

## Cấm lấy ví dụ làm input thật

Các giá trị trong `exampleCode`, `exampleFileName`, OCR example, cached formula/example trong workbook hoặc tài liệu tham khảo chỉ dùng để hiểu pattern/rule. Không được dùng chúng để điền bất kỳ field runtime nào còn thiếu như `DuAn`, `GoiThau`, `PhapNhan`, `NhaThau`, `ParentContractCode`, `ContractSequence`, `DocumentSequence`, `ExpiryDateYYMMDD`.

Nếu field trong `requiredForCode` thiếu evidence trực tiếp từ user, metadata hiện có, prefix cũ hợp lệ hoặc nội dung file, phải trả `needs_user_input` và hỏi user. Không được suy ra `TTDN`, `CTC`, sequence `01`, ngày hết hạn, hoặc parent contract code từ ví dụ mẫu.

Ví dụ sai cần chặn:

- User nói: “Hồ sơ thanh toán đợt 1, hợp đồng 01 CTC, dự án R02” nhưng không nói pháp nhân/ParentContractCode.
- Agent không được tự tạo `R02_TTDN_CTC_CTR_01` chỉ vì matrix có ví dụ `M01_TTDN_CTC_CTR_01_IPC_01`.
- Kết quả đúng là `needs_user_input`, hỏi `ParentContractCode` hoặc `PhapNhan` của hợp đồng.

## Quy trình bắt buộc

1. Nhận tên/path/metadata/nội dung và yêu cầu user.
2. Đọc master data liên quan một lần cho mỗi batch.
3. Phân loại một `documentTypeCode`; ghi evidence/confidence và không trộn ví dụ giữa các dòng nghiệp vụ.
4. Tra duy nhất `rules[documentTypeCode]` trong matrix.
5. Nếu không có executable rule, trả `unsupported`; không tự sáng tác pattern.
6. Thu thập đúng các trường trong `requiredForCode`, không yêu cầu thêm metadata chỉ vì cột Yes trong sheet.
7. Với mã con hợp đồng, ưu tiên `ParentContractCode`; không tái dựng mã cha nếu user đã cung cấp mã cha hợp lệ.
8. Xác thực các mã master mà rule trực tiếp sử dụng.
9. Nếu thiếu input, gom vào `missingFields`; batch thì hỏi một lần.
10. Gọi engine:

```bash
python scripts/document_code_engine.py --input '<json>'
```

Hoặc truyền JSON qua stdin. Không tự nối mã bằng LLM.
11. Chỉ chấp nhận output `status=ready` từ engine.
12. Trả đúng schema, gồm `DocumentCode`, `components`, `runtimeFields`, `inheritedFields`, `validation`, evidence và warnings.

## Quy tắc filename được hiểu từ sheet

Mã hồ sơ là identity. Mô tả và revision thuộc tên file, không thuộc DocumentCode. Khi xây filename ở skill upload, chỉ nối các phần không rỗng; không tạo dấu `_` thừa. Revision như `Rev01` chỉ dùng khi user/file cung cấp hoặc chính sách dòng yêu cầu.

## Trạng thái

- `ready`: engine render và validate thành công.
- `needs_user_input`: thiếu input trực tiếp cho code hoặc master match mơ hồ.
- `invalid_master_data`: mã direct input không tồn tại/không Active.
- `unsupported`: HoSo chưa có executable rule.
- `no_code`: nghiệp vụ nguồn ghi rõ không phát hành file/mã.

## Cấm

- Không gọi SharePoint write action.
- Không tự nối chuỗi mã ngoài engine.
- Không yêu cầu lại chi tiết nằm trong ParentContractCode hợp lệ.
- Không biến metadata tùy chọn thành điều kiện tạo mã.
- Không phát minh mã, sequence, ngày hoặc revision.
- Không sửa, đổi tên, copy/upload file hoặc tạo folder.
