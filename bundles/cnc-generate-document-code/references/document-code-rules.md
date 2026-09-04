# CNC Document Code Rules

## Năm thành phần chuẩn hóa

| Trường | Master |
|---|---|
| DuAn | CNC_MD_Projects.ProjectCode |
| LoaiTaiLieu | CNC_MD_DocumentTypes.DocumentTypeCode |
| GoiThau | CNC_MD_Packages.PackageCode |
| PhapNhan | CNC_MD_LegalEntities.LegalEntityCode |
| NhaThau | CNC_MD_Contractors.ContractorCode |

Thành phần không có trong mã trả `null`.

## Cấu trúc

- Tài liệu chung dự án: `[DuAn]_[LoaiTaiLieu]`.
- Tài liệu theo gói: `[DuAn]_[LoaiTaiLieu]_[GoiThau]`.
- Tài liệu theo gói và nhà thầu: `[DuAn]_[LoaiTaiLieu]_[GoiThau]_[NhaThau]`.
- Hợp đồng: `[DuAn]_[PhapNhan]_[NhaThau]_CTR_[STT]`.
- Hồ sơ theo hợp đồng: `[MaHopDong]_[LoaiTaiLieu]_[STT]` khi cần STT.
- Chứng thư bảo lãnh: theo cấu trúc nghiệp vụ được xác nhận; ngày YYMMDD lấy từ hồ sơ.

## Thành phần bắt buộc

- COP, MPP: DuAn, LoaiTaiLieu.
- PKG, TEN, PTE, INV, TDO, BOQ, TOR, TEV: DuAn, LoaiTaiLieu, GoiThau.
- BID, TCQ, LOI, LOA: DuAn, LoaiTaiLieu, GoiThau, NhaThau.
- CTR: DuAn, PhapNhan, NhaThau, LoaiTaiLieu, STT.
- IPC, VO, APL, FAC: mã cha hợp đồng, LoaiTaiLieu và STT khi cần.
- TEB, APB, PPB, WRB: thành phần theo hồ sơ bảo lãnh và quy tắc được user xác nhận.
- PR, RFQ, QUO, COR, PO, GRN: thành phần do ngữ cảnh/user xác định; mọi mã dùng phải khớp master.

## Ghép mã

- Separator `_`.
- Không có token rỗng.
- Không thêm giá trị giả cho thành phần không dùng.
- STT, ngày và revision không thuộc năm metadata.
