import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "local_file_pipeline.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pipeline", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scan_excludes_temporary_files_and_hashes_sources(tmp_path):
    p = load_module()
    src = tmp_path / "source"
    src.mkdir()
    (src / "real.txt").write_text("hello", encoding="utf-8")
    (src / "~$lock.xlsx").write_text("temp", encoding="utf-8")
    out = p.scan_folder(src, recursive=True, exclude_patterns=["~$*", "*.tmp"])
    assert [x["relativePath"] for x in out["files"]] == ["real.txt"]
    assert len(out["files"][0]["sha256"]) == 64
    assert out["excluded"][0]["relativePath"] == "~$lock.xlsx"


def test_plan_applies_agent_old_prefix_decision_and_routes_destination(tmp_path):
    p = load_module()
    scan = {"sourceRoot": str(tmp_path), "files": [{"relativePath": "M02_TDO_MEP02_Bao cao.pdf", "size": 3, "sha256": "a" * 64}]}
    codes = {
        "M02_TDO_MEP02_Bao cao.pdf": {
            "status": "ready",
            "DocumentCode": "M01_BID_MEP01_CTC",
            "components": {"DuAn": "M01", "LoaiTaiLieu": "BID", "GoiThau": "MEP01", "PhapNhan": None, "NhaThau": "CTC"},
            "fileNameDecision": {"status": "agent_decided", "oldPrefixToRemove": "M02_TDO_MEP02", "cleanBaseName": "Bao cao"},
        }
    }
    routes = {"BID": "02. TENDERING/04. BID"}
    plan = p.build_plan(scan, codes, routes, "1xx")
    f = plan["files"][0]
    assert f["detectedOldPrefix"] is None
    assert f["oldPrefixToRemove"] == "M02_TDO_MEP02"
    assert f["fileNameDecisionSource"] == "agent"
    assert f["newFileName"] == "M01_BID_MEP01_CTC_Bao cao.pdf"
    assert f["destinationRelativePath"] == "1xx/02. TENDERING/04. BID"
    assert plan["state"] == "planned"


def test_plan_keeps_original_stem_without_agent_decision(tmp_path):
    p = load_module()
    scan = {"sourceRoot": str(tmp_path), "files": [{"relativePath": "M02_TDO_MEP02_Bao cao.pdf", "size": 1, "sha256": "a" * 64}]}
    result = {"status": "ready", "DocumentCode": "M01_TDO_MEP01", "components": {"DuAn": "M01", "LoaiTaiLieu": "TDO", "GoiThau": "MEP01", "PhapNhan": None, "NhaThau": None}}
    plan = p.build_plan(scan, {"M02_TDO_MEP02_Bao cao.pdf": result}, {"TDO": "02. TENDERING/02. ITB"}, "1xx")
    f = plan["files"][0]
    assert f["detectedOldPrefix"] is None
    assert f["oldPrefixToRemove"] is None
    assert f["fileNameDecisionSource"] == "original"
    assert f["newFileName"] == "M01_TDO_MEP01_M02_TDO_MEP02_Bao cao.pdf"


def test_plan_blocks_when_agent_marks_filename_decision_needed(tmp_path):
    p = load_module()
    scan = {"sourceRoot": str(tmp_path), "files": [{"relativePath": "old_name.pdf", "size": 1, "sha256": "a" * 64}]}
    result = {
        "status": "ready",
        "DocumentCode": "M01_TDO_MEP01",
        "components": {"DuAn": "M01", "LoaiTaiLieu": "TDO", "GoiThau": "MEP01", "PhapNhan": None, "NhaThau": None},
        "fileNameDecision": {"status": "needs_user_input"},
    }
    plan = p.build_plan(scan, {"old_name.pdf": result}, {"TDO": "02. TENDERING/02. ITB"}, "1xx")
    assert plan["files"][0]["state"] == "needs_user_input"
    assert plan["files"][0]["reason"] == "FILENAME_DECISION_REQUIRED"


def test_plan_detects_collision_before_staging(tmp_path):
    p = load_module()
    scan = {"sourceRoot": str(tmp_path), "files": [
        {"relativePath": "a/Bao cao.pdf", "size": 1, "sha256": "a" * 64},
        {"relativePath": "b/Bao cao.pdf", "size": 1, "sha256": "b" * 64},
    ]}
    result = {"status": "ready", "DocumentCode": "M01_TEV_MEP01", "components": {"DuAn": "M01", "LoaiTaiLieu": "TEV", "GoiThau": "MEP01", "PhapNhan": None, "NhaThau": None}}
    plan = p.build_plan(scan, {"a/Bao cao.pdf": result, "b/Bao cao.pdf": result}, {"TEV": "02. TENDERING/07. BEV"}, "1xx")
    assert len(plan["collisions"]) == 1
    assert plan["state"] == "blocked"


def test_plan_accepts_batch_engine_result_envelope(tmp_path):
    p = load_module()
    scan = {"sourceRoot": str(tmp_path), "files": [{"relativePath": "a.pdf", "size": 1, "sha256": "a" * 64}]}
    result = {"status": "ready", "DocumentCode": "M01_COP", "components": {"DuAn": "M01", "LoaiTaiLieu": "COP", "GoiThau": None, "PhapNhan": None, "NhaThau": None}}
    batch = {"status": "batch", "results": {"a.pdf": result}, "summary": {"total": 1, "ready": 1}}
    plan = p.build_plan(scan, p.unwrap_code_results(batch), {"COP": "01. PRE-TENDER/01. COP"}, "1xx")
    assert plan["files"][0]["DocumentCode"] == "M01_COP"
    assert plan["state"] == "planned"


def test_stage_requires_confirmed_plan_and_preserves_source(tmp_path):
    p = load_module()
    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("abc", encoding="utf-8")
    digest = p.sha256_file(f)
    plan = {"schemaVersion": 1, "operationId": "op1", "state": "planned", "sourceRoot": str(src), "files": [{"sourceRelativePath": "a.txt", "sourceSize": 3, "sourceSha256": digest, "newFileName": "M01_COP_a.txt", "state": "ready"}], "collisions": []}
    try:
        p.stage_plan(plan, tmp_path / "stage")
        assert False, "must reject unconfirmed plan"
    except p.PipelineError as e:
        assert e.code == "PLAN_NOT_CONFIRMED"
    plan["state"] = "confirmed"
    manifest = p.stage_plan(plan, tmp_path / "stage")
    assert f.exists() and f.read_text(encoding="utf-8") == "abc"
    staged = Path(manifest["files"][0]["stagingPath"])
    assert staged.name == "M01_COP_a.txt" and p.sha256_file(staged) == digest


def test_stage_rejects_source_changed_after_confirmation(tmp_path):
    p = load_module()
    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.txt"
    f.write_text("new", encoding="utf-8")
    plan = {"schemaVersion": 1, "operationId": "op1", "state": "confirmed", "sourceRoot": str(src), "files": [{"sourceRelativePath": "a.txt", "sourceSize": 3, "sourceSha256": "0" * 64, "newFileName": "M01_COP_a.txt", "state": "ready"}], "collisions": []}
    try:
        p.stage_plan(plan, tmp_path / "stage")
        assert False
    except p.PipelineError as e:
        assert e.code == "SOURCE_CHANGED"


def test_cleanup_only_removes_fully_verified_operation(tmp_path):
    p = load_module()
    op = tmp_path / "op"
    op.mkdir()
    (op / "x").write_text("x")
    manifest = {"state": "staged", "files": [{"uploadState": "verified"}]}
    try:
        p.cleanup_operation(manifest, op)
        assert False
    except p.PipelineError as e:
        assert e.code == "NOT_FULLY_VERIFIED"
    manifest["state"] = "verified"
    p.cleanup_operation(manifest, op)
    assert not op.exists()
