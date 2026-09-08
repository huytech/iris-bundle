#!/usr/bin/env python3
"""SharePoint helpers for CNC package folders.

This script exists so agents do not recreate ad-hoc Graph code during CNC
package creation. It performs deterministic preview/create/verify operations for
one package folder and the configured template.

Usage:
  python scripts/sp_cnc_package_ops.py preview --config config/sharepoint.json --template config/package-folder-template.json --package "TTG.001"
  python scripts/sp_cnc_package_ops.py create  --config config/sharepoint.json --template config/package-folder-template.json --package "TTG.001"

Authentication:
  Uses the local Microsoft 365 delegated token by default, or env M365_TOKEN_PATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULT_TOKEN_PATH = Path.home() / "AppData" / "Roaming" / "ttg-os" / "ttg-os-home" / "microsoft365" / "delegated-token.json"
INVALID_NAME_CHARS = set('"*:<>?/\\|')
BATCH_LIMIT = 20


class SpError(RuntimeError):
    pass


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def token() -> str:
    token_path = Path(os.environ.get("M365_TOKEN_PATH", DEFAULT_TOKEN_PATH))
    data = read_json(token_path)
    access_token = data.get("access_token")
    if not access_token:
        raise SpError(f"No access_token in {token_path}")
    return access_token


def req(method: str, url: str, body=None, ok=(200, 201, 204)):
    headers = {"Authorization": "Bearer " + token()}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        if e.code in ok:
            return json.loads(text) if text else None
        raise SpError(f"HTTP {e.code} {method} {url}: {text}")


def enc_path(path: str) -> str:
    return urllib.parse.quote(path.strip("/"), safe="/")


def site_parts(site_url: str):
    parsed = urllib.parse.urlparse(site_url)
    if not parsed.netloc or not parsed.path:
        raise SpError(f"Invalid siteUrl: {site_url}")
    return parsed.netloc, parsed.path.rstrip("/")


def resolve_site(site_url: str):
    host, path = site_parts(site_url)
    return req("GET", f"{GRAPH}/sites/{host}:{path}")


def resolve_drive(site_url: str, library_name: str):
    site = resolve_site(site_url)
    drives = req("GET", f"{GRAPH}/sites/{site['id']}/drives").get("value", [])
    for drive in drives:
        if drive.get("name", "").casefold() == library_name.casefold():
            return drive
    names = [d.get("name") for d in drives]
    raise SpError(f"Library not found: {library_name}. Available: {names}")


def item_by_path(drive_id: str, path: str):
    url = f"{GRAPH}/drives/{drive_id}/root:/{enc_path(path)}"
    try:
        return req("GET", url)
    except SpError as e:
        if "HTTP 404" in str(e):
            return None
        raise


def items_by_path(drive_id: str, paths: list[str]):
    found = {}
    for start in range(0, len(paths), BATCH_LIMIT):
        chunk = paths[start:start + BATCH_LIMIT]
        requests = [
            {"id": str(index), "method": "GET", "url": f"/drives/{drive_id}/root:/{enc_path(path)}"}
            for index, path in enumerate(chunk)
        ]
        try:
            responses = req("POST", f"{GRAPH}/$batch", body={"requests": requests}).get("responses", [])
        except SpError:
            for path in chunk:
                found[path] = item_by_path(drive_id, path)
            continue
        by_id = {str(response.get("id")): response for response in responses}
        for index, path in enumerate(chunk):
            response = by_id.get(str(index))
            if response is None:
                raise SpError(f"Graph batch omitted response for {path}")
            status = response.get("status")
            if status == 200:
                found[path] = response.get("body")
            elif status == 404:
                found[path] = None
            else:
                found[path] = item_by_path(drive_id, path)
    return found


def create_folder(drive_id: str, parent_path: str, name: str):
    url = f"{GRAPH}/drives/{drive_id}/root:/{enc_path(parent_path)}:/children" if parent_path else f"{GRAPH}/drives/{drive_id}/root/children"
    body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
    return req("POST", url, body=body)


def validate_package_name(name: str, config: dict):
    trimmed = name.strip() if config.get("trimOuterWhitespace", True) else name
    forbidden = set(config.get("forbiddenNames", []))
    invalid = set(config.get("invalidCharacters", list(INVALID_NAME_CHARS)))
    if not trimmed:
        raise SpError("Package folder name is empty")
    if any(ch in invalid for ch in trimmed):
        raise SpError(f"Package folder name contains invalid SharePoint character: {trimmed}")
    if trimmed.endswith((" ", ".")):
        raise SpError(f"Package folder name ends with space/dot: {trimmed}")
    if trimmed in forbidden:
        raise SpError(f"Package folder name is forbidden by config: {trimmed}")
    return trimmed


def required_paths(root: str, package: str, template: dict):
    base = f"{root.strip('/')}/{package}" if root.strip("/") else package
    paths = [base]
    for folder in template.get("folders", []):
        paths.append(f"{base}/{folder['path'].strip('/')}")
    return paths


def split_parent(path: str):
    if "/" not in path.strip("/"):
        return "", path.strip("/")
    parent, name = path.strip("/").rsplit("/", 1)
    return parent, name


def preview(config: dict, template: dict, package_name: str):
    package = validate_package_name(package_name, config)
    drive = resolve_drive(config["siteUrl"], config["libraryName"])
    root = config["packageRootPath"].strip("/")
    paths = required_paths(root, package, template)
    items = items_by_path(drive["id"], paths)
    existing = [path for path in paths if items[path]]
    missing = [path for path in paths if not items[path]]
    result = {
        "siteUrl": config["siteUrl"],
        "libraryName": config["libraryName"],
        "driveId": drive["id"],
        "packageRootPath": root,
        "packageFolderName": package,
        "totalRequired": len(paths),
        "existing": existing,
        "missing": missing,
        "needsCreateOrUpdate": bool(missing),
        "verified": not missing,
    }
    result["planHash"] = package_plan_hash(result)
    return result


def package_plan_hash(plan: dict):
    value = {key: plan.get(key) for key in ("siteUrl", "libraryName", "packageRootPath", "packageFolderName", "missing")}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def create_from_plan(config: dict, template: dict, plan: dict):
    if plan.get("planHash") != package_plan_hash(plan):
        raise SpError("Package plan hash is missing or invalid; run preview again")
    for key in ("siteUrl", "libraryName", "packageRootPath"):
        if plan.get(key) != config.get(key):
            raise SpError(f"Package plan {key} does not match config")
    current = preview(config, template, plan["packageFolderName"])
    approved = set(plan.get("missing", []))
    unapproved = [path for path in current["missing"] if path not in approved]
    if unapproved:
        raise SpError(f"Package tree changed after confirmation; preview again: {unapproved}")
    drive_id = current["driveId"]
    created = []
    for path in required_paths(current["packageRootPath"], current["packageFolderName"], template):
        if path not in current["missing"]:
            continue
        parent, name = split_parent(path)
        create_folder(drive_id, parent, name)
        created.append(path)
    after = preview(config, template, current["packageFolderName"])
    return {"packageFolderName": current["packageFolderName"], "created": created, "missing": after["missing"], "verified": after["verified"]}


def create(config: dict, template: dict, package_name: str):
    before = preview(config, template, package_name)
    drive_id = before["driveId"]
    created, already_existing = [], []
    missing = set(before["missing"])
    # Iterate required paths in template order. Parents appear before children.
    for path in required_paths(before["packageRootPath"], before["packageFolderName"], template):
        if path not in missing:
            already_existing.append(path)
            continue
        parent, name = split_parent(path)
        create_folder(drive_id, parent, name)
        created.append(path)
    after = preview(config, template, package_name)
    return {
        "siteUrl": before["siteUrl"],
        "libraryName": before["libraryName"],
        "packageRootPath": before["packageRootPath"],
        "packageFolderName": before["packageFolderName"],
        "created": created,
        "existing": already_existing,
        "missing": after["missing"],
        "verified": after["verified"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["preview", "create"])
    base = Path(__file__).parents[1]
    ap.add_argument("--config", default=str(base / "config/package-sharepoint.json"))
    ap.add_argument("--template", default=str(base / "config/package-folder-template.json"))
    ap.add_argument("--package", dest="package_name")
    ap.add_argument("--plan")
    ap.add_argument("--output")
    args = ap.parse_args(argv)
    try:
        config = read_json(args.config)
        template = read_json(args.template)
        if config.get("libraryName") == "__REQUIRED__" or config.get("packageRootPath") == "__REQUIRED__":
            raise SpError("libraryName/packageRootPath is __REQUIRED__; ask user first")
        if args.command == "preview":
            if not args.package_name:
                raise SpError("preview requires --package")
            result = preview(config, template, args.package_name)
        elif args.plan:
            result = create_from_plan(config, template, read_json(args.plan))
        elif args.package_name:
            result = create(config, template, args.package_name)
        else:
            raise SpError("create requires --plan or --package")
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
