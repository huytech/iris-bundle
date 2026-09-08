#!/usr/bin/env python3
"""Prepare read-only CNC upload context in one concurrent operation."""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import local_file_pipeline
import master_data_snapshot
import sp_cnc_package_ops

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def inspect(args: argparse.Namespace) -> dict:
    workspace = Path(args.workspace).resolve()
    output_dir = (workspace / args.output_dir).resolve()
    try:
        output_dir.relative_to(workspace)
    except ValueError as error:
        raise RuntimeError(f"Output directory must stay inside workspace: {output_dir}") from error
    output_dir.mkdir(parents=True, exist_ok=True)
    master_config = master_data_snapshot.load(args.master_config)
    package_config = sp_cnc_package_ops.read_json(args.package_config)
    package_template = sp_cnc_package_ops.read_json(args.package_template)
    with ThreadPoolExecutor(max_workers=3) as executor:
        scan_future = executor.submit(local_file_pipeline.scan_folder, args.source)
        master_future = executor.submit(master_data_snapshot.refresh, master_config)
        package_future = executor.submit(sp_cnc_package_ops.preview, package_config, package_template, args.package)
        scan = scan_future.result()
        masters = master_future.result()
        package = package_future.result()
    scan_path = output_dir / "scan.json"
    master_path = output_dir / "master-snapshot.json"
    package_path = output_dir / "package-plan.json"
    write_json(scan_path, scan)
    write_json(master_path, masters)
    write_json(package_path, package)
    summary = {
        "schemaVersion": 1,
        "sourceRoot": scan["sourceRoot"],
        "files": scan["files"],
        "excluded": scan["excluded"],
        "masterData": {
            "fetchedAt": masters["fetchedAt"],
            "snapshotPath": str(master_path),
            "counts": {key: len(value["items"]) for key, value in masters["lists"].items()},
        },
        "package": {
            "packageFolderName": package["packageFolderName"],
            "verified": package["verified"],
            "existing": package["existing"],
            "missing": package["missing"],
            "planPath": str(package_path),
        },
        "scanPath": str(scan_path),
    }
    write_json(output_dir / "prepare-context.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["inspect"])
    parser.add_argument("--source", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output-dir", default=".cnc-work")
    base = Path(__file__).parents[1]
    parser.add_argument("--master-config", default=str(base / "config/master-data.json"))
    parser.add_argument("--package-config", default=str(base / "config/package-sharepoint.json"))
    parser.add_argument("--package-template", default=str(base / "config/package-folder-template.json"))
    args = parser.parse_args()
    try:
        result = inspect(args)
        print(json.dumps({
            "status": "ready",
            "fileCount": len(result["files"]),
            "masterCounts": result["masterData"]["counts"],
            "package": result["package"]["packageFolderName"],
            "packageVerified": result["package"]["verified"],
            "missingFolderCount": len(result["package"]["missing"]),
            "contextPath": str(Path(args.workspace).resolve() / args.output_dir / "prepare-context.json"),
            "masterSnapshotPath": result["masterData"]["snapshotPath"],
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
