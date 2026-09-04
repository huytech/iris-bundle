import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("upload_ops", ROOT / "scripts" / "sp_cnc_upload_ops.py")
upload_ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload_ops)


def test_items_by_path_chunks_graph_batches(monkeypatch):
    calls = []

    def fake_req(method, url, body=None, headers=None, ok=(200, 201, 204)):
        calls.append((method, url, body))
        return {"responses": [
            {"id": request["id"], "status": 200, "body": {"name": request["url"]}}
            for request in body["requests"]
        ]}

    monkeypatch.setattr(upload_ops, "req", fake_req)
    paths = [f"folder/file-{index}.pdf" for index in range(21)]
    result = upload_ops.items_by_path("drive", paths)
    assert len(calls) == 2
    assert [len(call[2]["requests"]) for call in calls] == [20, 1]
    assert list(result) == paths


def test_check_collisions_preserves_per_file_results(monkeypatch):
    monkeypatch.setattr(upload_ops, "resolve_drive", lambda *_: {"id": "drive"})
    monkeypatch.setattr(upload_ops, "items_by_path", lambda _drive, paths: {path: ({"id": "taken"} if path.endswith("b.pdf") else None) for path in paths})
    plan = {"files": [
        {"state": "staged", "sourceRelativePath": "a.pdf", "destinationRelativePath": "pkg", "newFileName": "a.pdf"},
        {"state": "staged", "sourceRelativePath": "b.pdf", "destinationRelativePath": "pkg", "newFileName": "b.pdf"},
    ]}
    result = upload_ops.check_collisions({"siteUrl": "site", "libraryName": "lib", "destinationRootPath": "root"}, plan)
    assert result["ok"] is False
    assert [item["exists"] for item in result["checked"]] == [False, True]
    assert result["collisions"][0]["sourceRelativePath"] == "b.pdf"


def test_items_by_path_falls_back_when_graph_batch_fails(monkeypatch):
    monkeypatch.setattr(upload_ops, "req", lambda *_args, **_kwargs: (_ for _ in ()).throw(upload_ops.SpError("batch unavailable")))
    monkeypatch.setattr(upload_ops, "item_by_path", lambda _drive, path: {"name": path})
    paths = ["a.pdf", "b.pdf"]
    assert upload_ops.items_by_path("drive", paths) == {
        "a.pdf": {"name": "a.pdf"},
        "b.pdf": {"name": "b.pdf"},
    }
