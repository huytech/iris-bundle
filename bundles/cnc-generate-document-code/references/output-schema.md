# Output Schema

Mỗi file trả một object có rule, năm metadata, runtime fields và validation riêng.

```json
{
  "source": {"name": "Bao cao tai chinh.pdf", "path": null},
  "classification": {
    "documentTypeCode": "BID",
    "confidence": 0.93,
    "evidence": ["Filename contains: hồ sơ dự thầu"]
  },
  "rule": {
    "ruleId": "BID",
    "codePattern": "{DuAn}_{LoaiTaiLieu}_{GoiThau}_{NhaThau}"
  },
  "components": {
    "DuAn": "M01",
    "LoaiTaiLieu": "BID",
    "GoiThau": "MEP01",
    "PhapNhan": null,
    "NhaThau": "CTC"
  },
  "runtimeFields": {
    "ContractSequence": null,
    "DocumentSequence": null,
    "ExpiryDateYYMMDD": null,
    "ParentContractCode": null
  },
  "DocumentCode": "M01_BID_MEP01_CTC",
  "missingFields": [],
  "ambiguousFields": [],
  "warnings": [],
  "validation": {
    "noPlaceholders": true,
    "forbiddenMetadataAbsent": true,
    "patternMatched": true
  },
  "status": "ready"
}
```

## Ví dụ TEB

```json
{
  "classification": {
    "documentTypeCode": "TEB",
    "confidence": 0.98,
    "evidence": ["OCR heading: Bảo lãnh dự thầu"]
  },
  "rule": {
    "ruleId": "TEB",
    "codePattern": "{DuAn}_{LoaiTaiLieu}_{NhaThau}_{ExpiryDateYYMMDD}"
  },
  "components": {
    "DuAn": "M01",
    "LoaiTaiLieu": "TEB",
    "GoiThau": null,
    "PhapNhan": null,
    "NhaThau": "CTC"
  },
  "runtimeFields": {"ExpiryDateYYMMDD": "260728"},
  "DocumentCode": "M01_TEB_CTC_260728",
  "missingFields": [],
  "ambiguousFields": [],
  "warnings": [],
  "validation": {
    "noPlaceholders": true,
    "forbiddenMetadataAbsent": true,
    "patternMatched": true
  },
  "status": "ready"
}
```

## Ví dụ thiếu dữ liệu

Nếu user nói “Hồ sơ thanh toán đợt 1, hợp đồng 01 CTC, dự án R02” nhưng không cung cấp pháp nhân hoặc `ParentContractCode`, không được lấy `TTDN` từ ví dụ mẫu. Phải trả `needs_user_input` với `missingFields` gồm `ParentContractCode` hoặc `PhapNhan`.

```json
{
  "source": {"name": "HSDT_CTC.pdf", "path": null},
  "classification": {
    "documentTypeCode": "BID",
    "confidence": 0.88,
    "evidence": ["Filename contains: HSDT", "Contractor matched: CTC"]
  },
  "rule": {
    "ruleId": "BID",
    "codePattern": "{DuAn}_{LoaiTaiLieu}_{GoiThau}_{NhaThau}"
  },
  "components": {
    "DuAn": null,
    "LoaiTaiLieu": "BID",
    "GoiThau": null,
    "PhapNhan": null,
    "NhaThau": "CTC"
  },
  "runtimeFields": {},
  "DocumentCode": null,
  "missingFields": ["DuAn", "GoiThau"],
  "ambiguousFields": [],
  "warnings": [],
  "validation": {
    "noPlaceholders": false,
    "forbiddenMetadataAbsent": true,
    "patternMatched": false
  },
  "status": "needs_user_input"
}
```

`ambiguousFields` item:

```json
{
  "field": "GoiThau",
  "reason": "Multiple active master records match MEP01",
  "candidates": [
    {"code": "MEP01", "name": "Phòng cháy chữa cháy"},
    {"code": "MEP01", "name": "Chiếu sáng mặt dựng"}
  ]
}
```
