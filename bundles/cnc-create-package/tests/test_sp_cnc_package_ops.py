import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("package_ops", ROOT / "scripts" / "sp_cnc_package_ops.py")
package_ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_ops)


def test_preview_batches_required_path_reads(monkeypatch):
    monkeypatch.setattr(package_ops, "resolve_drive", lambda *_: {"id": "drive"})
    seen = []

    def fake_items(_drive, paths):
        seen.extend(paths)
        return {path: ({"id": path} if path.endswith("existing") else None) for path in paths}

    monkeypatch.setattr(package_ops, "items_by_path", fake_items)
    template = {"folders": [{"path": "existing"}, {"path": "missing"}]}
    result = package_ops.preview({"siteUrl": "site", "libraryName": "lib", "packageRootPath": "root"}, template, "PKG")
    assert seen == ["root/PKG", "root/PKG/existing", "root/PKG/missing"]
    assert result["existing"] == ["root/PKG/existing"]
    assert result["missing"] == ["root/PKG", "root/PKG/missing"]


def test_create_uses_preview_missing_set_without_rechecking_each_path(monkeypatch):
    previews = [
        {"siteUrl": "site", "libraryName": "lib", "driveId": "drive", "packageRootPath": "root", "packageFolderName": "PKG", "missing": ["root/PKG", "root/PKG/child"], "verified": False},
        {"siteUrl": "site", "libraryName": "lib", "driveId": "drive", "packageRootPath": "root", "packageFolderName": "PKG", "missing": [], "verified": True},
    ]
    monkeypatch.setattr(package_ops, "preview", lambda *_: previews.pop(0))
    monkeypatch.setattr(package_ops, "item_by_path", lambda *_: (_ for _ in ()).throw(AssertionError("unexpected per-path read")))
    created = []
    monkeypatch.setattr(package_ops, "create_folder", lambda drive, parent, name: created.append((drive, parent, name)))
    result = package_ops.create({}, {"folders": [{"path": "child"}]}, "PKG")
    assert created == [("drive", "root", "PKG"), ("drive", "root/PKG", "child")]
    assert result["verified"] is True


def test_items_by_path_falls_back_when_graph_batch_fails(monkeypatch):
    monkeypatch.setattr(package_ops, "req", lambda *_args, **_kwargs: (_ for _ in ()).throw(package_ops.SpError("batch unavailable")))
    monkeypatch.setattr(package_ops, "item_by_path", lambda _drive, path: {"name": path})
    paths = ["root/PKG", "root/PKG/child"]
    assert package_ops.items_by_path("drive", paths) == {
        "root/PKG": {"name": "root/PKG"},
        "root/PKG/child": {"name": "root/PKG/child"},
    }
