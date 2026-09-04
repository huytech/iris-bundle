#!/usr/bin/env python3
"""Safe local scan/plan/stage/verify/cleanup pipeline for CNC files."""
from __future__ import annotations
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

DEFAULT_EXCLUDES = ["~$*", "*.tmp", "*.part", "*.crdownload", ".DS_Store", "Thumbs.db"]
INVALID_NAME_CHARS = re.compile(r'["*:<>?/\\|]')

# NOTE: old-prefix detection is intentionally NOT implemented here.
# The agent must decide any prefix removal during preview preparation and pass that
# decision in code_results[relativePath]["fileNameDecision"]. The script only
# applies the explicit decision; otherwise it keeps the original filename stem.


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


def _excluded(rel: str, patterns: list[str]) -> bool:
    name = Path(rel).name
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p) for p in patterns)


def scan_folder(source, recursive=True, exclude_patterns=None):
    root = Path(source).resolve()
    if not root.exists():
        raise PipelineError("SOURCE_NOT_FOUND", str(root))
    if not root.is_dir():
        raise PipelineError("SOURCE_NOT_DIRECTORY", str(root))
    patterns = list(exclude_patterns or DEFAULT_EXCLUDES)
    iterator = root.rglob("*") if recursive else root.glob("*")
    files, excluded = [], []
    for path in sorted(iterator, key=lambda p: p.as_posix().casefold()):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _excluded(rel, patterns):
            excluded.append({"relativePath": rel, "reason": "excluded_pattern"})
            continue
        st = path.stat()
        files.append({"relativePath": rel, "size": st.st_size, "modifiedTime": st.st_mtime,
                      "sha256": sha256_file(path)})
    return {"schemaVersion": 1, "sourceRoot": str(root), "scannedAt": utc_now(), "files": files, "excluded": excluded}


def safe_filename(name: str):
    if not name or INVALID_NAME_CHARS.search(name) or name.endswith((" ", ".")):
        raise PipelineError("INVALID_FILENAME", name)
    return name


def _filename_decision(result: dict, rel: str):
    """Return (old_prefix_to_remove, clean_base_name, decision_source).

    The script does not infer prefix structure from the filename. It accepts only
    an explicit agent decision under fileNameDecision. If absent, the full
    original stem is preserved.
    """
    original_stem = Path(rel).stem
    decision = result.get("fileNameDecision") or {}
    status = decision.get("status", "keep_original")
    if status in {"needs_user_input", "ambiguous", "blocked"}:
        raise PipelineError("FILENAME_DECISION_REQUIRED", rel)
    old_prefix = decision.get("oldPrefixToRemove")
    clean = decision.get("cleanBaseName", original_stem)
    if clean is None:
        clean = ""
    clean = str(clean).strip(" _-")
    if old_prefix is not None:
        old_prefix = str(old_prefix).strip(" _-") or None
    return old_prefix, clean, "agent" if decision else "original"


def build_plan(scan, code_results, routing, package_folder_name):
    package = str(package_folder_name).strip()
    if not package or INVALID_NAME_CHARS.search(package):
        raise PipelineError("INVALID_PACKAGE_FOLDER", package)
    planned = []
    seen = {}
    collisions = []
    for item in scan.get("files", []):
        rel = item["relativePath"]
        result = code_results.get(rel)
        if not result or result.get("status") != "ready":
            planned.append({"sourceRelativePath": rel, "state": "needs_user_input", "codeResult": result})
            continue
        components = result.get("components", {})
        dtype = components.get("LoaiTaiLieu") or result.get("documentTypeCode")
        route = routing.get(dtype)
        if not route:
            planned.append({"sourceRelativePath": rel, "state": "needs_user_input", "reason": "NO_FOLDER_ROUTE", "codeResult": result})
            continue
        try:
            old_prefix, clean, decision_source = _filename_decision(result, rel)
        except PipelineError as e:
            planned.append({"sourceRelativePath": rel, "state": "needs_user_input", "reason": e.code, "codeResult": result})
            continue
        ext = Path(rel).suffix
        new_name = safe_filename(result["DocumentCode"] + ("_" + clean if clean else "") + ext)
        dest = str(PurePosixPath(package) / PurePosixPath(route))
        key = (dest.casefold(), new_name.casefold())
        entry = {"sourceRelativePath": rel, "sourceSize": item["size"], "sourceSha256": item["sha256"],
                 "detectedOldPrefix": None, "oldPrefixToRemove": old_prefix, "fileNameDecisionSource": decision_source,
                 "DocumentCode": result["DocumentCode"], "newFileName": new_name,
                 "packageFolderName": package, "destinationRelativePath": dest,
                 "metadata": {k: components.get(k) for k in ("DuAn", "LoaiTaiLieu", "GoiThau", "PhapNhan", "NhaThau")},
                 "state": "ready"}
        if key in seen:
            collisions.append({"destinationRelativePath": dest, "newFileName": new_name, "sources": [seen[key], rel]})
        else:
            seen[key] = rel
        planned.append(entry)
    return {"schemaVersion": 1, "operationId": "cnc-" + uuid.uuid4().hex[:12], "createdAt": utc_now(),
            "sourceRoot": scan["sourceRoot"], "packageFolderName": package, "state": "blocked" if collisions else "planned",
            "files": planned, "collisions": collisions}


def confirm_plan(plan: dict) -> dict:
    if plan.get("state") != "planned":
        raise PipelineError("PLAN_NOT_PLANNABLE", plan.get("state", ""))
    if plan.get("collisions"):
        raise PipelineError("PLAN_HAS_COLLISIONS", "Resolve collisions first")
    out = json.loads(json.dumps(plan))
    out["state"] = "confirmed"
    out["confirmedAt"] = utc_now()
    return out


def _ensure_outside_source(source_root: Path, staging_root: Path):
    try:
        staging_root.relative_to(source_root)
        raise PipelineError("STAGING_INSIDE_SOURCE", str(staging_root))
    except ValueError:
        pass


def stage_plan(plan: dict, staging_root):
    if plan.get("state") != "confirmed":
        raise PipelineError("PLAN_NOT_CONFIRMED", "Confirm preview first")
    if plan.get("collisions"):
        raise PipelineError("PLAN_HAS_COLLISIONS", "Resolve collisions first")
    source_root = Path(plan["sourceRoot"]).resolve()
    stage_root = Path(staging_root).resolve()
    _ensure_outside_source(source_root, stage_root)
    op_dir = stage_root / plan["operationId"]
    files_dir = op_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(json.dumps(plan))
    manifest["state"] = "staging"
    manifest["stagingRoot"] = str(op_dir)
    try:
        for entry in manifest["files"]:
            if entry.get("state") != "ready":
                continue
            src = (source_root / Path(entry["sourceRelativePath"])).resolve()
            try:
                src.relative_to(source_root)
            except ValueError:
                raise PipelineError("PATH_TRAVERSAL", str(src))
            if not src.is_file():
                raise PipelineError("SOURCE_NOT_FOUND", str(src))
            if src.stat().st_size != entry["sourceSize"] or sha256_file(src) != entry["sourceSha256"]:
                raise PipelineError("SOURCE_CHANGED", str(src))
            dst = files_dir / entry["newFileName"]
            if dst.exists():
                raise PipelineError("STAGING_COLLISION", str(dst))
            partial = dst.with_name(dst.name + ".partial")
            shutil.copy2(src, partial)
            if sha256_file(partial) != entry["sourceSha256"]:
                raise PipelineError("COPY_HASH_MISMATCH", str(src))
            os.replace(partial, dst)
            entry["stagingPath"] = str(dst)
            entry["stagingSha256"] = entry["sourceSha256"]
            entry["state"] = "staged"
            entry["uploadState"] = "pending"
        manifest["state"] = "staged"
        manifest["stagedAt"] = utc_now()
        (op_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
    except Exception:
        # Preserve operation directory for diagnostics.
        raise


def verify_staging(manifest: dict):
    source_root = Path(manifest["sourceRoot"])
    errors = []
    for e in manifest.get("files", []):
        if e.get("state") not in {"staged", "verified"}:
            continue
        src = source_root / e["sourceRelativePath"]
        dst = Path(e["stagingPath"])
        if not src.is_file() or sha256_file(src) != e["sourceSha256"]:
            errors.append({"file": e["sourceRelativePath"], "error": "SOURCE_CHANGED"})
        if not dst.is_file() or sha256_file(dst) != e["sourceSha256"]:
            errors.append({"file": e["sourceRelativePath"], "error": "STAGING_MISMATCH"})
    return {"valid": not errors, "errors": errors}


def mark_uploaded(manifest: dict, source_relative_path: str, sharepoint_url: str, verified: bool):
    found = False
    for e in manifest.get("files", []):
        if e.get("sourceRelativePath") == source_relative_path:
            e["sharePointUrl"] = sharepoint_url
            e["uploadState"] = "verified" if verified else "uploaded"
            found = True
            break
    if not found:
        raise PipelineError("FILE_NOT_IN_MANIFEST", source_relative_path)
    if all(e.get("state") != "staged" or e.get("uploadState") == "verified" for e in manifest.get("files", [])):
        manifest["state"] = "verified"
        manifest["verifiedAt"] = utc_now()
    return manifest


def cleanup_operation(manifest: dict, operation_dir):
    if manifest.get("state") != "verified" or any(e.get("state") == "staged" and e.get("uploadState") != "verified" for e in manifest.get("files", [])):
        raise PipelineError("NOT_FULLY_VERIFIED", "Keep staging for retry")
    shutil.rmtree(Path(operation_dir))


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(data, path=None):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        print(text)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--source", required=True)
    s.add_argument("--output")
    s.add_argument("--no-recursive", action="store_true")
    q = sub.add_parser("plan")
    q.add_argument("--scan", required=True)
    q.add_argument("--codes", required=True)
    q.add_argument("--routing", required=True)
    q.add_argument("--package-folder", required=True)
    q.add_argument("--output")
    c = sub.add_parser("confirm")
    c.add_argument("--plan", required=True)
    c.add_argument("--output")
    t = sub.add_parser("stage")
    t.add_argument("--plan", required=True)
    t.add_argument("--staging-root", required=True)
    t.add_argument("--output")
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    x = sub.add_parser("cleanup")
    x.add_argument("--manifest", required=True)
    a = ap.parse_args()
    try:
        if a.cmd == "scan":
            out = scan_folder(a.source, not a.no_recursive)
        elif a.cmd == "plan":
            routes = _read(a.routing).get("routingByDocumentType", _read(a.routing))
            out = build_plan(_read(a.scan), _read(a.codes), routes, a.package_folder)
        elif a.cmd == "confirm":
            out = confirm_plan(_read(a.plan))
        elif a.cmd == "stage":
            out = stage_plan(_read(a.plan), a.staging_root)
        elif a.cmd == "verify":
            out = verify_staging(_read(a.manifest))
        elif a.cmd == "cleanup":
            m = _read(a.manifest)
            cleanup_operation(m, Path(a.manifest).parent)
            out = {"status": "cleaned"}
        _write(out, getattr(a, "output", None))
        return 0
    except PipelineError as e:
        print(json.dumps({"status": "error", "code": e.code, "message": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
