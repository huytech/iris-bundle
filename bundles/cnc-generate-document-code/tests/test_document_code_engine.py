import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("engine", ROOT / "scripts" / "document_code_engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
MATRIX = engine.load_matrix(ROOT / "config" / "document-code-matrix.json")

def ready(code, **values):
    r = engine.generate(code, values, MATRIX)
    assert r["status"] == "ready", r
    return r

def test_all_direct_codes():
    cases = [
        ("COP", {"DuAn":"M01"}, "M01_COP"),
        ("MPP", {"DuAn":"M01"}, "M01_MPP"),
        ("PKG", {"DuAn":"M01","GoiThau":"MEP01"}, "M01_PKG_MEP01"),
        ("TEN", {"DuAn":"M01","GoiThau":"MEP01"}, "M01_TEN_MEP01"),
        ("PTE", {"DuAn":"M01","GoiThau":"MEP01"}, "M01_PTE_MEP01"),
        ("INV", {"DuAn":"M01","GoiThau":"MEP01"}, "M01_INV_MEP01"),
        ("TDO", {"DuAn":"M01","GoiThau":"MEP01"}, "M01_TDO_MEP01"),
        ("BID", {"DuAn":"M01","GoiThau":"MEP01","NhaThau":"CTC"}, "M01_BID_MEP01_CTC"),
        ("TOR", {"DuAn":"M01","GoiThau":"MEP01"}, "M01_TOR_MEP01"),
        ("TCQ", {"DuAn":"M01","GoiThau":"MEP01","NhaThau":"CTC"}, "M01_TCQ_MEP01_CTC"),
        ("TEV", {"DuAn":"M01","GoiThau":"MEP01"}, "M01_TEV_MEP01"),
        ("LOI", {"DuAn":"M01","GoiThau":"MEP01","NhaThau":"CTC"}, "M01_LOI_MEP01_CTC"),
        ("LOA", {"DuAn":"M01","GoiThau":"MEP01","NhaThau":"CTC"}, "M01_LOA_MEP01_CTC"),
        ("CTR", {"DuAn":"R01","PhapNhan":"TTDN","NhaThau":"CTC","ContractSequence":"1"}, "R01_TTDN_CTC_CTR_01"),
        ("TEB", {"DuAn":"M01","NhaThau":"CTC","ExpiryDateYYMMDD":"260728"}, "M01_TEB_CTC_260728"),
        ("QUO", {"DuAn":"M01","NhaThau":"CTC"}, "M01_QUO_CTC"),
        ("COR", {"DuAn":"M01","NhaThau":"CTC"}, "M01_COR_CTC"),
    ]
    for typ, values, expected in cases:
        assert ready(typ, **values)["DocumentCode"] == expected

def test_contract_children_need_no_component_details():
    parent = "R02_TTDN_CTC_CTR_01"
    fac = ready("FAC", ParentContractCode=parent)
    assert fac["DocumentCode"] == parent + "_FAC"
    assert fac["components"] == {"DuAn":"R02","LoaiTaiLieu":"FAC","GoiThau":None,"PhapNhan":"TTDN","NhaThau":"CTC"}
    assert ready("IPC", ParentContractCode=parent, DocumentSequence="1")["DocumentCode"] == parent + "_IPC_01"
    assert ready("VO", ParentContractCode=parent, DocumentSequence="2")["DocumentCode"] == parent + "_VO_02"
    assert ready("PL", ParentContractCode=parent, DocumentSequence="3")["DocumentCode"] == parent + "_PL_03"

def test_optional_package_metadata_does_not_change_child_code():
    parent="M01_TTDN_CTC_CTR_01"
    r=ready("FAC", ParentContractCode=parent, GoiThau="MEP01")
    assert r["DocumentCode"] == parent + "_FAC"
    assert r["components"]["GoiThau"] == "MEP01"

def test_apl_alias_renders_sheet_token_pl():
    r=ready("APL", ParentContractCode="M01_TTDN_CTC_CTR_01", DocumentSequence="1")
    assert r["documentTypeCode"] == "PL"
    assert r["DocumentCode"].endswith("_PL_01")

def test_teb_never_requests_or_renders_package():
    r=ready("TEB", DuAn="M01", NhaThau="CTC", ExpiryDateYYMMDD="260728", GoiThau="MEP01")
    assert r["DocumentCode"] == "M01_TEB_CTC_260728"
    assert r["components"]["GoiThau"] is None

def test_missing_and_unsupported():
    r=engine.generate("TEB", {"DuAn":"M01","NhaThau":"CTC"}, MATRIX)
    assert r["status"] == "needs_user_input" and r["missingFields"] == ["ExpiryDateYYMMDD"]
    assert engine.generate("BOQ", {}, MATRIX)["status"] == "unsupported"
    assert engine.generate("PPB", {}, MATRIX)["status"] == "unsupported"

def test_batch_matches_individual_generation_and_summarizes_statuses():
    payload = {"items": [
        {"id": "fac.pdf", "documentTypeCode": "FAC", "values": {"ParentContractCode": "R02_TTDN_CTC_CTR_01"}},
        {"id": "teb.pdf", "documentTypeCode": "TEB", "values": {"DuAn": "M01", "NhaThau": "CTC"}},
        {"id": "boq.xlsx", "documentTypeCode": "BOQ", "values": {}},
    ]}
    batch = engine.generate_payload(payload, MATRIX)
    assert batch["status"] == "batch"
    assert batch["results"]["fac.pdf"] == engine.generate("FAC", payload["items"][0]["values"], MATRIX)
    assert batch["results"]["teb.pdf"]["status"] == "needs_user_input"
    assert batch["results"]["boq.xlsx"]["status"] == "unsupported"
    assert batch["summary"] == {"total": 3, "ready": 1, "needs_user_input": 1, "unsupported": 1}

def test_batch_rejects_duplicate_ids():
    payload = {"items": [
        {"id": "same.pdf", "documentTypeCode": "COP", "values": {"DuAn": "M01"}},
        {"id": "same.pdf", "documentTypeCode": "COP", "values": {"DuAn": "M02"}},
    ]}
    try:
        engine.generate_payload(payload, MATRIX)
        assert False, "duplicate ids must fail"
    except engine.CodeEngineError as error:
        assert "Duplicate batch item id" in str(error)

def test_invalid_parent_and_placeholders_rejected():
    r=engine.generate("FAC", {"ParentContractCode":"R02_TTDN_CTC_CTR_[STT]"}, MATRIX)
    assert r["status"] == "invalid" and r["DocumentCode"] is None

def test_detect_existing_prefix_uses_rules_and_master_snapshot():
    masters={
        "DuAn":{"M01","M02","R02"},
        "GoiThau":{"MEP01","MEP02"},
        "PhapNhan":{"TTDN","BDM"},
        "NhaThau":{"CTC","HB"}
    }
    r=engine.detect_existing_prefix("M02_TDO_MEP02_Bao_cao_tai_chinh.pdf",MATRIX,masters)
    assert r["status"] == "unique_match"
    assert r["prefix"] == "M02_TDO_MEP02"
    assert r["cleanBaseName"] == "Bao_cao_tai_chinh"
    assert r["ruleId"] == "TDO"

def test_detect_existing_prefix_handles_contract_child_and_no_partial_code():
    masters={"DuAn":{"M01"},"GoiThau":{"MEP01"},"PhapNhan":{"TTDN"},"NhaThau":{"CTC"}}
    child=engine.detect_existing_prefix("M01_TTDN_CTC_CTR_01_FAC_Bien_ban.pdf",MATRIX,masters)
    assert child["prefix"] == "M01_TTDN_CTC_CTR_01_FAC"
    assert child["ruleId"] == "FAC"
    partial=engine.detect_existing_prefix("M01_Bao_cao.pdf",MATRIX,masters)
    assert partial["status"] == "no_prefix"

def test_detect_existing_prefix_rejects_unknown_master_token():
    masters={"DuAn":{"M01"},"GoiThau":{"MEP01"},"PhapNhan":{"TTDN"},"NhaThau":{"CTC"}}
    r=engine.detect_existing_prefix("M99_TDO_MEP01_Ho_so.pdf",MATRIX,masters)
    assert r["status"] == "no_prefix"
