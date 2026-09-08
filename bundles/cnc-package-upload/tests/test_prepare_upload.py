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
