#!/usr/bin/env python3
"""SharePoint upload helpers for CNC staged upload plans.

Use this instead of creating ad-hoc Graph scripts in the workspace. The local
pipeline still owns scan/plan/confirm/stage/cleanup. This helper owns only
SharePoint-side collision check, upload, metadata patch, and verification.

Usage:
  python scripts/sp_cnc_upload_ops.py check-collisions --config config/sharepoint.json --plan staged-plan.json --output collisions.json
  python scripts/sp_cnc_upload_ops.py upload-plan      --config config/sharepoint.json --plan staged-plan.json --output uploaded-plan.json

Authentication:
  Uses the local Microsoft 365 delegated token by default, or env M365_TOKEN_PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULT_TOKEN_PATH = Path.home() / "AppData" / "Roaming" / "ttg-os" / "ttg-os-home" / "microsoft365" / "delegated-token.json"
METADATA_COLUMNS = ("DuAn", "LoaiTaiLieu", "GoiThau", "PhapNhan", "NhaThau")
BATCH_LIMIT = 20


class SpError(RuntimeError):
    pass


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(data, path: str | Path | None):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        print(text)


def token() -> str:
    token_path = Path(os.environ.get("M365_TOKEN_PATH", DEFAULT_TOKEN_PATH))
    data = read_json(token_path)
    access_token = data.get("access_token")
    if not access_token:
        raise SpError(f"No access_token in {token_path}")
    return access_token


def req(method: str, url: str, body=None, headers=None, ok=(200, 201, 204)):
    h = {"Authorization": "Bearer " + token()}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=h)
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


def load_config(path: str | Path):
    config = read_json(path)
    sp = config.get("sharePoint", config)
    if sp.get("libraryName") == "__REQUIRED__" or sp.get("destinationRootPath") == "__REQUIRED__":
        raise SpError("libraryName/destinationRootPath is __REQUIRED__; ask user first")
    return sp


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
                # Preserve the original single-request behavior and diagnostics
                # for throttling or service errors on one batch member.
                found[path] = item_by_path(drive_id, path)
    return found


def upload_file(drive_id: str, dest_path: str, local_path: str):
    data = Path(local_path).read_bytes()
    url = f"{GRAPH}/drives/{drive_id}/root:/{enc_path(dest_path)}:/content"
    return req("PUT", url, body=data, headers={"Content-Type": "application/octet-stream"})


def update_item_metadata(drive_id: str, item_id: str, metadata: dict):
    # Null metadata fields are intentionally written as null to clear old values.
    fields = {k: metadata.get(k) for k in METADATA_COLUMNS}
    return req("PATCH", f"{GRAPH}/drives/{drive_id}/items/{item_id}/listItem/fields", body=fields)


def get_item_fields(drive_id: str, item_id: str):
    return req("GET", f"{GRAPH}/drives/{drive_id}/items/{item_id}/listItem/fields")


def destination_path(root: str, entry: dict):
    return f"{root.strip('/')}/{entry['destinationRelativePath'].strip('/')}/{entry['newFileName']}"


def check_collisions(config: dict, plan: dict):
    drive = resolve_drive(config["siteUrl"], config["libraryName"])
    root = config["destinationRootPath"]
    collisions = []
    checked = []
    entries = [entry for entry in plan.get("files", []) if entry.get("state") in {"ready", "staged"}]
    destinations = [destination_path(root, entry) for entry in entries]
    items = items_by_path(drive["id"], destinations)
    for entry, dest in zip(entries, destinations):
        item = items[dest]
        checked.append({"sourceRelativePath": entry.get("sourceRelativePath"), "destination": dest, "exists": bool(item)})
        if item:
            collisions.append({"sourceRelativePath": entry.get("sourceRelativePath"), "destination": dest, "itemId": item.get("id"), "webUrl": item.get("webUrl")})
    return {"driveId": drive["id"], "checked": checked, "collisions": collisions, "ok": not collisions}


def _metadata_matches(expected: dict, fields: dict):
    got = {k: fields.get(k) for k in METADATA_COLUMNS}
    ok = all((got[k] in (None, "") if expected.get(k) is None else got[k] == expected.get(k)) for k in METADATA_COLUMNS)
    return ok, got


def _upload_one(drive_id: str, root: str, entry: dict):
    dest = destination_path(root, entry)
    existing = item_by_path(drive_id, dest)
    if existing:
        raise SpError(f"Destination already exists, refusing overwrite: {dest}")
    item = upload_file(drive_id, dest, entry["stagingPath"])
    try:
        update_item_metadata(drive_id, item["id"], entry.get("metadata", {}))
        reread = item_by_path(drive_id, dest)
        fields = get_item_fields(drive_id, item["id"])
        meta_ok, got = _metadata_matches(entry.get("metadata", {}), fields)
        size_ok = (reread or {}).get("size") == entry.get("sourceSize")
        name_ok = (reread or {}).get("name") == entry.get("newFileName")
        if not reread or not name_ok or not size_ok or not meta_ok:
            raise SpError(f"Verify failed for {dest}; name_ok={name_ok}, size_ok={size_ok}, meta_ok={meta_ok}, got={got}")
        entry["sharePointUrl"] = item.get("webUrl") or reread.get("webUrl")
        entry["sharePointItemId"] = item.get("id")
        entry["uploadState"] = "verified"
        entry.pop("uploadError", None)
        entry["verifiedMetadata"] = got
        entry["verifiedSize"] = reread.get("size")
        return {"sourceRelativePath": entry.get("sourceRelativePath"), "destination": dest, "webUrl": entry["sharePointUrl"], "metadata": got}
    except Exception:
        # The file may exist without correct metadata. Mark partial failure for retry/manual handling.
        raise


def upload_plan(config: dict, plan: dict):
    drive = resolve_drive(config["siteUrl"], config["libraryName"])
    root = config["destinationRootPath"]
    uploaded, errors = [], []
    out_plan = json.loads(json.dumps(plan))
    for entry in out_plan.get("files", []):
        if entry.get("state") != "staged":
            continue
        try:
            uploaded.append(_upload_one(drive["id"], root, entry))
        except Exception as ex:
            entry["uploadState"] = "failed"
            entry["uploadError"] = str(ex)
            errors.append({"sourceRelativePath": entry.get("sourceRelativePath"), "error": str(ex)})
    staged_entries = [e for e in out_plan.get("files", []) if e.get("state") == "staged"]
    out_plan["state"] = "verified" if not errors and all(e.get("uploadState") == "verified" for e in staged_entries) else "partial_failure"
    return {"plan": out_plan, "summary": {"state": out_plan["state"], "uploaded": uploaded, "errors": errors}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check-collisions", "upload-plan"])
    ap.add_argument("--config", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--output")
    ap.add_argument("--summary-output")
    args = ap.parse_args(argv)
    try:
        config = load_config(args.config)
        plan = read_json(args.plan)
        if args.command == "check-collisions":
            result = check_collisions(config, plan)
            write_json(result, args.output)
            return 0 if result["ok"] else 2
        result = upload_plan(config, plan)
        write_json(result["plan"], args.output)
        if args.summary_output:
            write_json(result["summary"], args.summary_output)
        else:
            print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        return 0 if result["summary"]["state"] == "verified" else 2
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
