import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("prepare_upload", ROOT / "scripts" / "prepare_upload.py")
prepare_upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_upload)


def test_inspect_combines_read_only_results(monkeypatch, tmp_path):
    monkeypatch.setattr(prepare_upload.master_data_snapshot, "load", lambda _: {"siteUrl": "site"})
    monkeypatch.setattr(prepare_upload.sp_cnc_package_ops, "read_json", lambda path: {"folders": []} if "template" in str(path) else {"siteUrl": "site"})
    monkeypatch.setattr(prepare_upload.local_file_pipeline, "scan_folder", lambda _: {"sourceRoot": "source", "files": [{"relativePath": "a.pdf"}], "excluded": []})
    monkeypatch.setattr(prepare_upload.master_data_snapshot, "refresh", lambda _: {"fetchedAt": "time", "lists": {"projects": {"items": [{"code": "R02"}]}}})
    monkeypatch.setattr(prepare_upload.sp_cnc_package_ops, "preview", lambda *_: {"packageFolderName": "TTG.003", "verified": False, "existing": [], "missing": ["root/TTG.003"]})
    args = SimpleNamespace(workspace=tmp_path, output_dir="work", master_config="master", package_config="package", package_template="template", source="source", package="TTG.003")
    result = prepare_upload.inspect(args)
    assert result["masterData"]["counts"] == {"projects": 1}
    assert result["package"]["missing"] == ["root/TTG.003"]
    assert (tmp_path / "work" / "prepare-context.json").is_file()


def test_parse_values_rejects_invalid_and_keeps_explicit_fields():
    assert prepare_upload.parse_values(["DuAn=M01", "DocumentSequence=1"]) == {"DuAn": "M01", "DocumentSequence": "1"}
    try:
        prepare_upload.parse_values(["missing-separator"])
        assert False
    except RuntimeError as error:
        assert "Invalid code value" in str(error)


def test_parse_values_normalizes_agent_business_aliases():
    assert prepare_upload.parse_values([
        "Project=M02",
        "ContractParty=CTC",
        "ContractSequence=01",
        "PaymentSequence=1",
    ]) == {
        "DuAn": "M02",
        "NhaThau": "CTC",
        "ContractSequence": "01",
        "DocumentSequence": "1",
    }


def test_parse_values_normalizes_explicit_business_sequence_phrases():
    assert prepare_upload.parse_values([
        "ContractSequence=hợp đồng 01",
        "DocumentSequence=đợt 1",
    ]) == {
        "ContractSequence": "01",
        "DocumentSequence": "1",
    }


def test_destination_package_is_not_a_tender_package_alias():
    assert prepare_upload.parse_values(["Package=TTG.004"]) == {"DestinationPackage": "TTG.004"}
    assert prepare_upload.parse_values(["TenderPackage=MEP01"]) == {"GoiThau": "MEP01"}
    values, ignored = prepare_upload.separate_destination_package({"DestinationPackage": "ttg.004"}, "TTG.004")
    assert values == {}
    assert ignored == ["DestinationPackage"]
    try:
        prepare_upload.separate_destination_package({"DestinationPackage": "TTG.003"}, "TTG.004")
        assert False
    except RuntimeError as error:
        assert "conflicts" in str(error)


def test_parse_values_rejects_unknown_and_conflicting_fields():
    for values, expected in ((["Mystery=M02"], "Unsupported business field"), (["Project=M01", "DuAn=M02"], "Conflicting values")):
        try:
            prepare_upload.parse_values(values)
            assert False
        except RuntimeError as error:
            assert expected in str(error)


def test_business_values_infer_sequence_and_build_parent_contract():
    matrix = prepare_upload.document_code_engine.load_matrix(ROOT / "config" / "document-code-matrix.json")
    values = prepare_upload.prepare_business_values(
        {"DuAn": "R02", "PhapNhan": "TTDN", "NhaThau": "CTC", "ContractSequence": "1"},
        "Hồ sơ thanh toán đợt 1",
        matrix,
    )
    assert values["DocumentSequence"] == "1"
    assert values["ParentContractCode"] == "R02_TTDN_CTC_CTR_01"


def test_sequence_inference_requires_one_unambiguous_ordinal():
    assert prepare_upload.infer_document_sequence("Thanh toán lần thứ 2") == "2"
    assert prepare_upload.infer_document_sequence("Hồ sơ kỳ 03") == "03"
    assert prepare_upload.infer_document_sequence("Đợt 1 và đợt 2") is None
    assert prepare_upload.infer_document_sequence("Hồ sơ thanh toán") is None


def test_master_values_resolve_names_and_reject_unknown_codes():
    snapshot = {"lists": {
        "projects": {"items": [{"code": "R02", "name": "Dự án Nam Ô Heritage"}]},
        "legalEntities": {"items": [{"code": "TTDN", "name": "Trung Thủy Đà Nẵng"}]},
        "contractors": {"items": [{"code": "CTC", "name": "Công ty CTC"}]},
        "packages": {"items": []},
    }}
    values, issues = prepare_upload.validate_business_values(
        {"DuAn": "Nam O Heritage", "PhapNhan": "TTDN", "NhaThau": "CTC"}, snapshot
    )
    assert issues == []
    assert values == {"DuAn": "R02", "PhapNhan": "TTDN", "NhaThau": "CTC"}
    _, issues = prepare_upload.validate_business_values({"DuAn": "M99"}, snapshot)
    assert issues[0]["field"] == "DuAn"
    assert issues[0]["status"] == "not_found"


def test_snapshot_cache_requires_fresh_timestamp_and_lists():
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    assert prepare_upload.snapshot_is_fresh({"fetchedAt": now, "lists": {"projects": {"items": []}}}, 300)
    assert not prepare_upload.snapshot_is_fresh({"fetchedAt": now, "lists": {}}, 300)
    assert not prepare_upload.snapshot_is_fresh({"fetchedAt": "invalid", "lists": {"projects": {}}}, 300)


def test_snapshot_cache_requires_configured_list_identity():
    config = {"lists": {"projects": {}, "contractors": {}}}
    complete = {"lists": {
        "projects": {"listId": "p", "items": []},
        "contractors": {"listId": "c", "items": []},
    }}
    assert prepare_upload.snapshot_has_required_lists(complete, config)
    assert not prepare_upload.snapshot_has_required_lists({"lists": {"projects": {"listId": "p", "items": []}}}, config)
    assert prepare_upload.master_config_fingerprint(config) != prepare_upload.master_config_fingerprint({"siteUrl": "other", **config})


def test_request_context_recovers_only_unique_explicit_master_codes():
    snapshot = {"lists": {
        "projects": {"items": [{"code": "M01"}, {"code": "M02"}]},
        "packages": {"items": []},
        "legalEntities": {"items": [{"code": "TTDN"}]},
        "contractors": {"items": [{"code": "CTC"}, {"code": "HB"}]},
    }}
    values = prepare_upload.infer_master_values_from_request(
        {}, "Hồ sơ Hợp đồng 01 CTC, dự án M02", snapshot
    )
    assert values == {"DuAn": "M02", "NhaThau": "CTC", "ContractSequence": "01"}
    ambiguous = prepare_upload.infer_master_values_from_request({}, "So sánh CTC và HB tại M02", snapshot)
    assert "NhaThau" not in ambiguous


def test_values_for_ipc_ignores_destination_package_as_tender_package():
    matrix = prepare_upload.document_code_engine.load_matrix(ROOT / "config" / "document-code-matrix.json")
    values, ignored = prepare_upload.values_for_rule(
        {"DuAn": "M02", "GoiThau": "TTG.004", "NhaThau": "CTC", "ContractSequence": "01"},
        matrix["rules"]["IPC"],
    )
    assert values == {"DuAn": "M02", "NhaThau": "CTC", "ContractSequence": "01"}
    assert ignored == ["GoiThau"]


def test_parent_contract_rules_filter_destination_package_without_dropping_valid_optional_tender_package():
    matrix = prepare_upload.document_code_engine.load_matrix(ROOT / "config" / "document-code-matrix.json")
    for code in ("IPC", "VO", "PL", "FAC"):
        values, destination_ignored = prepare_upload.separate_destination_package(
            {"DestinationPackage": "TTG.004", "GoiThau": "MEP01"}, "TTG.004"
        )
        filtered, rule_ignored = prepare_upload.values_for_rule(values, matrix["rules"][code])
        assert destination_ignored == ["DestinationPackage"]
        if code == "IPC":
            assert "GoiThau" not in filtered
            assert rule_ignored == ["GoiThau"]
        else:
            assert filtered["GoiThau"] == "MEP01"


def test_plan_batch_checks_collisions_before_confirmation(monkeypatch, tmp_path):
    scan_path = tmp_path / "scan.json"
    snapshot_path = tmp_path / "master.json"
    package_path = tmp_path / "package.json"
    context_path = tmp_path / "prepare-context.json"
    scan_path.write_text('{"sourceRoot":"source","files":[{"relativePath":"a.pdf","size":1,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],"excluded":[]}', encoding="utf-8")
    snapshot_path.write_text('{"lists":{"projects":{"items":[{"code":"R02"}]},"packages":{"items":[]},"legalEntities":{"items":[{"code":"TTDN"}]},"contractors":{"items":[{"code":"CTC"}]}}}', encoding="utf-8")
    package_path.write_text('{}', encoding="utf-8")
    context_path.write_text(__import__("json").dumps({"scanPath": str(scan_path), "masterData": {"snapshotPath": str(snapshot_path)}, "package": {"packageFolderName": "TTG.003", "planPath": str(package_path)}}), encoding="utf-8")
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "load_config", lambda *_: {})
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "check_collisions", lambda *_: {"ok": False, "checked": [], "collisions": [{"sourceRelativePath": "a.pdf"}]})
    args = SimpleNamespace(context=str(context_path), document_type="Hồ sơ thanh toán", request_context="", value=["ParentContractCode=R02_TTDN_CTC_CTR_01", "DocumentSequence=1"])
    result = prepare_upload.plan_batch(args)
    assert result["status"] == "blocked"
    assert result["collisionCount"] == 1


def test_plan_batch_blocks_empty_source_before_any_remote_collision_check(monkeypatch, tmp_path):
    scan_path = tmp_path / "scan.json"
    snapshot_path = tmp_path / "master.json"
    context_path = tmp_path / "prepare-context.json"
    scan_path.write_text('{"sourceRoot":"source","files":[],"excluded":[]}', encoding="utf-8")
    snapshot_path.write_text('{"lists":{}}', encoding="utf-8")
    context_path.write_text(__import__("json").dumps({"scanPath": str(scan_path), "masterData": {"snapshotPath": str(snapshot_path)}, "package": {"packageFolderName": "TTG.004", "planPath": "package.json"}}), encoding="utf-8")
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "check_collisions", lambda *_: (_ for _ in ()).throw(AssertionError("must not check collisions")))
    args = SimpleNamespace(context=str(context_path), document_type="IPC", request_context="", value=[])
    result = prepare_upload.plan_batch(args)
    assert result == {
        "status": "blocked", "reason": "NO_SOURCE_FILES", "fileCount": 0,
        "message": "Không có file hợp lệ trong thư mục nguồn để lập preview.",
    }


def test_plan_batch_returns_business_question_before_collision_check(monkeypatch, tmp_path):
    scan_path = tmp_path / "scan.json"
    snapshot_path = tmp_path / "master.json"
    context_path = tmp_path / "prepare-context.json"
    scan_path.write_text('{"sourceRoot":"source","files":[{"relativePath":"a.pdf","size":1,"sha256":"aa"}],"excluded":[]}', encoding="utf-8")
    snapshot_path.write_text('{"lists":{}}', encoding="utf-8")
    context_path.write_text(__import__("json").dumps({"scanPath": str(scan_path), "masterData": {"snapshotPath": str(snapshot_path)}, "package": {"packageFolderName": "TTG.003", "planPath": "package.json"}}), encoding="utf-8")
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "check_collisions", lambda *_: (_ for _ in ()).throw(AssertionError("must not check collisions")))
    args = SimpleNamespace(context=str(context_path), document_type="IPC", request_context="hồ sơ thanh toán đợt 1", value=[])
    result = prepare_upload.plan_batch(args)
    assert result["status"] == "needs_user_input"
    assert result["missingFields"] == ["ParentContractCode"]
    assert "ParentContractCode" not in result["question"]
    assert "DocumentSequence" not in result["question"]


def test_plan_batch_preserves_invalid_code_errors(monkeypatch, tmp_path):
    scan_path = tmp_path / "scan.json"
    snapshot_path = tmp_path / "master.json"
    context_path = tmp_path / "prepare-context.json"
    scan_path.write_text('{"sourceRoot":"source","files":[{"relativePath":"a.pdf","size":1,"sha256":"aa"}],"excluded":[]}', encoding="utf-8")
    snapshot_path.write_text('{"lists":{"projects":{"items":[{"code":"M02"}]},"legalEntities":{"items":[{"code":"TTDN"}]},"contractors":{"items":[{"code":"CTC"}]},"packages":{"items":[]}}}', encoding="utf-8")
    context_path.write_text(__import__("json").dumps({"scanPath": str(scan_path), "masterData": {"snapshotPath": str(snapshot_path)}, "package": {"packageFolderName": "TTG.003", "planPath": "package.json"}}), encoding="utf-8")
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "check_collisions", lambda *_: (_ for _ in ()).throw(AssertionError("must not check collisions")))
    args = SimpleNamespace(
        context=str(context_path), document_type="IPC", request_context="",
        value=["ParentContractCode=M02_TTDN_CTC_CTR_01", "DocumentSequence=đợt đầu"],
    )
    result = prepare_upload.plan_batch(args)
    assert result["status"] == "invalid"
    assert result["reason"] == "CODE_GENERATION_INVALID"
    assert result["errors"] == ["Invalid DocumentSequence: 'đợt đầu'"]
    assert "missingFields" not in result


def test_plan_batch_rejects_parent_components_outside_master(monkeypatch, tmp_path):
    scan_path = tmp_path / "scan.json"
    snapshot_path = tmp_path / "master.json"
    context_path = tmp_path / "prepare-context.json"
    scan_path.write_text('{"sourceRoot":"source","files":[{"relativePath":"a.pdf","size":1,"sha256":"aa"}],"excluded":[]}', encoding="utf-8")
    snapshot_path.write_text('{"lists":{"projects":{"items":[{"code":"R02","name":"R02"}]},"legalEntities":{"items":[{"code":"TTDN","name":"TTDN"}]},"contractors":{"items":[{"code":"CTC","name":"CTC"}]},"packages":{"items":[]}}}', encoding="utf-8")
    context_path.write_text(__import__("json").dumps({"scanPath": str(scan_path), "masterData": {"snapshotPath": str(snapshot_path)}, "package": {"packageFolderName": "TTG.003", "planPath": "package.json"}}), encoding="utf-8")
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "check_collisions", lambda *_: (_ for _ in ()).throw(AssertionError("must not check collisions")))
    args = SimpleNamespace(context=str(context_path), document_type="IPC", request_context="đợt 1", value=["ParentContractCode=M99_TTDN_CTC_CTR_01"])
    result = prepare_upload.plan_batch(args)
    assert result["status"] == "needs_user_input"
    assert result["masterIssue"]["field"] == "DuAn"


def test_plan_batch_rejects_parent_code_conflicting_with_explicit_facts(monkeypatch, tmp_path):
    scan_path = tmp_path / "scan.json"
    snapshot_path = tmp_path / "master.json"
    context_path = tmp_path / "prepare-context.json"
    scan_path.write_text('{"sourceRoot":"source","files":[{"relativePath":"a.pdf","size":1,"sha256":"aa"}],"excluded":[]}', encoding="utf-8")
    snapshot_path.write_text('{"lists":{"projects":{"items":[{"code":"R02","name":"R02"},{"code":"M02","name":"M02"}]},"legalEntities":{"items":[{"code":"TTDN","name":"TTDN"}]},"contractors":{"items":[{"code":"CTC","name":"CTC"}]},"packages":{"items":[]}}}', encoding="utf-8")
    context_path.write_text(__import__("json").dumps({"scanPath": str(scan_path), "masterData": {"snapshotPath": str(snapshot_path)}, "package": {"packageFolderName": "TTG.003", "planPath": "package.json"}}), encoding="utf-8")
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "check_collisions", lambda *_: (_ for _ in ()).throw(AssertionError("must not check collisions")))
    args = SimpleNamespace(
        context=str(context_path), document_type="IPC", request_context="đợt 1",
        value=["ParentContractCode=R02_TTDN_CTC_CTR_01", "Project=M02"],
    )
    result = prepare_upload.plan_batch(args)
    assert result["status"] == "needs_user_input"
    assert result["conflictingFields"] == ["DuAn"]


def test_plan_batch_does_not_validate_irrelevant_tender_package_for_ipc(monkeypatch, tmp_path):
    scan_path = tmp_path / "scan.json"
    snapshot_path = tmp_path / "master.json"
    context_path = tmp_path / "prepare-context.json"
    scan_path.write_text('{"sourceRoot":"source","files":[{"relativePath":"a.pdf","size":1,"sha256":"aa"}],"excluded":[]}', encoding="utf-8")
    snapshot_path.write_text('{"lists":{"projects":{"items":[{"code":"M02","name":"M02"}]},"legalEntities":{"items":[{"code":"TTDN","name":"TTDN"}]},"contractors":{"items":[{"code":"CTC","name":"CTC"}]},"packages":{"items":[]}}}', encoding="utf-8")
    context_path.write_text(__import__("json").dumps({"scanPath": str(scan_path), "masterData": {"snapshotPath": str(snapshot_path)}, "package": {"packageFolderName": "TTG.004", "planPath": "package.json"}}), encoding="utf-8")
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "load_config", lambda *_: {})
    monkeypatch.setattr(prepare_upload.sp_cnc_upload_ops, "check_collisions", lambda *_: {"ok": True, "checked": [], "collisions": []})
    args = SimpleNamespace(
        context=str(context_path), document_type="IPC", request_context="Hồ sơ thanh toán đợt 1 Hợp đồng 01 CTC, dự án M02, pháp nhân TTDN",
        value=["DuAn=M02", "GoiThau=TTG.004", "PhapNhan=TTDN", "NhaThau=CTC", "ContractSequence=01"],
    )
    result = prepare_upload.plan_batch(args)
    assert result["status"] == "ready"
    assert result["ignoredFields"] == ["GoiThau"]
    assert "M02_TTDN_CTC_CTR_01_IPC_01" in result["previewMarkdown"]


def test_all_executable_document_types_have_routes():
    matrix = prepare_upload.document_code_engine.load_matrix(ROOT / "config" / "document-code-matrix.json")
    config = prepare_upload.local_file_pipeline._read(ROOT / "config" / "folder-routing.json")
    routed = set(config["routingByDocumentType"])
    intentionally_unrouted = set(config["intentionallyUnroutedDocumentTypes"])
    assert set(matrix["rules"]) - routed == intentionally_unrouted
    assert routed.isdisjoint(intentionally_unrouted)
