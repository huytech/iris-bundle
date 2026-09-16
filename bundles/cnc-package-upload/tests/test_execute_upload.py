import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("execute_upload", ROOT / "scripts" / "execute_upload.py")
execute_upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execute_upload)


def write_json(path: Path, value: dict):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def sample_plan(tmp_path: Path) -> tuple[dict, Path]:
    source = tmp_path / "source"
    source.mkdir()
    payload = b"hello"
    source_file = source / "a.pdf"
    source_file.write_bytes(payload)
    plan = {
        "schemaVersion": 1,
        "operationId": "cnc-test123",
        "createdAt": "2026-09-16T00:00:00+00:00",
        "sourceRoot": str(source),
        "packageFolderName": "ELV01",
        "state": "planned",
        "files": [
            {
                "sourceRelativePath": "a.pdf",
                "sourceSize": len(payload),
                "sourceSha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                "DocumentCode": "M01_TTDN_CTC_CTR_01",
                "newFileName": "M01_TTDN_CTC_CTR_01_a.pdf",
                "destinationRelativePath": "ELV01/03. CONTRACT/01. CTR",
                "metadata": {"DuAn": "M01", "LoaiTaiLieu": "CTR", "GoiThau": None, "PhapNhan": "TTDN", "NhaThau": "CTC"},
                "state": "ready",
            }
        ],
        "collisions": [],
    }
    return plan, source_file


def args(tmp_path: Path, confirmation_response: str) -> SimpleNamespace:
    return SimpleNamespace(
        package_plan=str(tmp_path / "package-plan.json"),
        upload_plan=str(tmp_path / "plan.json"),
        workspace=str(tmp_path / "workspace"),
        output_dir=".cnc-work/ELV01/execute",
        confirmation_response=confirmation_response,
    )


def prepare_files(tmp_path: Path, plan: dict):
    (tmp_path / "workspace").mkdir()
    write_json(tmp_path / "package-plan.json", {"packageFolderName": "ELV01"})
    write_json(tmp_path / "plan.json", plan)


def stub_external_ops(monkeypatch):
    created = {"called": False}
    monkeypatch.setattr(execute_upload.sp_cnc_package_ops, "read_json", lambda path: {})

    def create_from_plan(*_):
        created["called"] = True
        return {"packageFolderName": "ELV01", "verified": True, "created": []}

    monkeypatch.setattr(execute_upload.sp_cnc_package_ops, "create_from_plan", create_from_plan)
    monkeypatch.setattr(execute_upload.sp_cnc_upload_ops, "load_config", lambda path: {})
    monkeypatch.setattr(execute_upload.sp_cnc_upload_ops, "check_collisions", lambda *_: {"ok": True, "collisions": []})
    def upload_plan(_config, plan):
        verified = json.loads(json.dumps(plan))
        verified["state"] = "verified"
        for item in verified["files"]:
            item["uploadState"] = "verified"
        return {"plan": verified, "summary": {"state": "verified"}}

    monkeypatch.setattr(execute_upload.sp_cnc_upload_ops, "upload_plan", upload_plan)
    return created


def test_execute_rejects_empty_confirmation_before_creating_package(monkeypatch, tmp_path):
    plan, _ = sample_plan(tmp_path)
    prepare_files(tmp_path, plan)
    created = stub_external_ops(monkeypatch)
    try:
        execute_upload.execute(args(tmp_path, "{}"))
        assert False, "upload must require explicit user confirmation"
    except RuntimeError as error:
        assert "explicit ask_user_question confirmation" in str(error)
    assert created["called"] is False


def test_execute_accepts_matching_ask_user_confirmation(monkeypatch, tmp_path):
    plan, _ = sample_plan(tmp_path)
    prepare_files(tmp_path, plan)
    stub_external_ops(monkeypatch)
    response = {
        "answers": [
            {
                "id": execute_upload.expected_confirmation_id(plan["operationId"]),
                "selected": [execute_upload.CONFIRM_UPLOAD_LABEL],
            }
        ]
    }
    result = execute_upload.execute(args(tmp_path, json.dumps(response, ensure_ascii=False)))
    assert result["status"] == "success"
    assert (tmp_path / "workspace" / ".cnc-work" / "ELV01" / "execute" / "confirmed-plan.json").is_file()
