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


def test_create_from_plan_uses_only_approved_missing_paths(monkeypatch):
    config = {"siteUrl": "site", "libraryName": "lib", "packageRootPath": "root"}
    template = {"folders": [{"path": "child"}]}
    plan = {"siteUrl": "site", "libraryName": "lib", "driveId": "drive", "packageRootPath": "root", "packageFolderName": "PKG", "missing": ["root/PKG", "root/PKG/child"], "verified": False}
    plan["planHash"] = package_ops.package_plan_hash(plan)
    previews = [plan, {**plan, "missing": [], "verified": True}]
    monkeypatch.setattr(package_ops, "preview", lambda *_: previews.pop(0))
    created = []
    monkeypatch.setattr(package_ops, "create_folder", lambda drive, parent, name: created.append((drive, parent, name)))
    result = package_ops.create_from_plan(config, template, plan)
    assert created == [("drive", "root", "PKG"), ("drive", "root/PKG", "child")]
    assert result["verified"] is True


def test_create_updates_folder_description_metadata(monkeypatch):
    config = {
        "siteUrl": "site",
        "libraryName": "lib",
        "packageRootPath": "root",
        "folderMetadata": {
            "enabled": True,
            "descriptionField": "MoTaLoaiTaiLieu",
            "descriptionDisplayName": "Mô tả loại tài liệu",
            "mirrorDescriptionFields": ["_ExtendedDescription"],
        },
    }
    template = {"folders": [{"path": "01. PRE-TENDER/01. COP", "description": "Kế hoạch ngân sách cho dự án"}]}
    previews = [
        {"siteUrl": "site", "libraryName": "lib", "driveId": "drive", "packageRootPath": "root", "packageFolderName": "PKG", "missing": ["root/PKG", "root/PKG/01. PRE-TENDER", "root/PKG/01. PRE-TENDER/01. COP"], "verified": False},
        {"siteUrl": "site", "libraryName": "lib", "driveId": "drive", "packageRootPath": "root", "packageFolderName": "PKG", "missing": [], "verified": True},
    ]
    monkeypatch.setattr(package_ops, "preview", lambda *_: previews.pop(0))
    monkeypatch.setattr(package_ops, "create_folder", lambda *_: {"id": "created"})
    monkeypatch.setattr(package_ops, "ensure_text_column", lambda *_: {"status": "existing"})
    monkeypatch.setattr(
        package_ops,
        "items_by_path",
        lambda _drive, paths: {path: {"id": path.rsplit("/", 1)[-1]} for path in paths},
    )
    patched = []
    monkeypatch.setattr(package_ops, "update_item_fields", lambda drive, item, fields: patched.append((drive, item, fields)))
    monkeypatch.setattr(package_ops, "get_item_fields", lambda _drive, _item: {"MoTaLoaiTaiLieu": "Kế hoạch ngân sách cho dự án", "_ExtendedDescription": "Kế hoạch ngân sách cho dự án"})
    result = package_ops.create(config, template, "PKG")
    assert patched == [
        (
            "drive",
            "01. COP",
            {
                "MoTaLoaiTaiLieu": "Kế hoạch ngân sách cho dự án",
                "_ExtendedDescription": "Kế hoạch ngân sách cho dự án",
            },
        )
    ]
    assert result["metadataUpdated"] == [
        {
            "path": "root/PKG/01. PRE-TENDER/01. COP",
            "fields": {
                "MoTaLoaiTaiLieu": "Kế hoạch ngân sách cho dự án",
                "_ExtendedDescription": "Kế hoạch ngân sách cho dự án",
            },
            "verified": True,
        }
    ]
