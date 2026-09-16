#!/usr/bin/env python3
"""Execute one confirmed CNC package and upload plan in the required order."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import local_file_pipeline
import sp_cnc_package_ops
import sp_cnc_upload_ops

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def execute(args: argparse.Namespace) -> dict:
    workspace = Path(args.workspace).resolve()
    operation_dir = (workspace / args.output_dir).resolve()
    try:
        operation_dir.relative_to(workspace)
    except ValueError as error:
        raise RuntimeError(f"Output directory must stay inside workspace: {operation_dir}") from error
    operation_dir.mkdir(parents=True, exist_ok=True)
    base = Path(__file__).parents[1]
    package_config = sp_cnc_package_ops.read_json(base / "config/package-sharepoint.json")
    package_template = sp_cnc_package_ops.read_json(base / "config/package-folder-template.json")
    package_plan = sp_cnc_package_ops.read_json(args.package_plan)
    package_result = sp_cnc_package_ops.create_from_plan(package_config, package_template, package_plan)
    write(operation_dir / "package-result.json", package_result)
    if not package_result["verified"]:
        raise RuntimeError("Package tree verification failed")
    upload_plan = local_file_pipeline._read(args.upload_plan)
    confirmed = local_file_pipeline.confirm_plan(upload_plan)
    write(operation_dir / "confirmed-plan.json", confirmed)
    staged = local_file_pipeline.stage_plan(confirmed, operation_dir / "stage")
    write(operation_dir / "staged-plan.json", staged)
    upload_config = sp_cnc_upload_ops.load_config(base / "config/sharepoint.json")
    collisions = sp_cnc_upload_ops.check_collisions(upload_config, staged)
    write(operation_dir / "collision-check.json", collisions)
    if not collisions["ok"]:
        raise RuntimeError("Destination collision detected; upload stopped")
    uploaded = sp_cnc_upload_ops.upload_plan(upload_config, staged)
    write(operation_dir / "uploaded-plan.json", uploaded["plan"])
    write(operation_dir / "upload-summary.json", uploaded["summary"])
    if uploaded["summary"]["state"] != "verified":
        raise RuntimeError("Upload or metadata verification failed; staging retained")
    staging_dir = Path(staged["stagingRoot"])
    local_file_pipeline.cleanup_operation(uploaded["plan"], staging_dir)
    return {"status": "success", "package": package_result, "upload": uploaded["summary"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-plan", required=True)
    parser.add_argument("--upload-plan", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
