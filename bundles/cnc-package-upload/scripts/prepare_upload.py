#!/usr/bin/env python3
"""Prepare read-only CNC upload context in one concurrent operation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import document_code_engine
import local_file_pipeline
import master_data_snapshot
import sp_cnc_package_ops
import sp_cnc_upload_ops

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_workspace_path(workspace: Path, value: str) -> Path:
    candidate = (workspace / value).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as error:
        raise RuntimeError(f"Path must stay inside workspace: {candidate}") from error
    return candidate


def master_config_fingerprint(config: dict) -> str:
    relevant = {
        "siteUrl": config.get("siteUrl"),
        "activeStatus": config.get("activeStatus"),
        "lists": config.get("lists"),
    }
    encoded = json.dumps(relevant, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def snapshot_has_required_lists(snapshot: dict, config: dict) -> bool:
    lists = snapshot.get("lists")
    if not isinstance(lists, dict):
        return False
    for key in config.get("lists", {}):
        entry = lists.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("items"), list) or not entry.get("listId"):
            return False
    return True


def snapshot_is_fresh(snapshot: dict, max_age_seconds: int) -> bool:
    if max_age_seconds <= 0 or not snapshot.get("fetchedAt") or not snapshot.get("lists"):
        return False
    try:
        fetched = datetime.fromisoformat(snapshot["fetchedAt"].replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    age = (datetime.now(timezone.utc) - fetched.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= max_age_seconds


def load_or_refresh_masters(config: dict, cache_path: Path, max_age_seconds: int) -> tuple[dict, bool]:
    if cache_path.is_file():
        try:
            cache = local_file_pipeline._read(cache_path)
            cached = cache.get("snapshot", {})
            if (
                cache.get("schemaVersion") == 1
                and cache.get("configFingerprint") == master_config_fingerprint(config)
                and snapshot_has_required_lists(cached, config)
                and snapshot_is_fresh(cached, max_age_seconds)
            ):
                return cached, True
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    refreshed = master_data_snapshot.refresh(config)
    if not snapshot_has_required_lists(refreshed, config):
        raise RuntimeError("Refreshed master snapshot is incomplete")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache_path, {
        "schemaVersion": 1,
        "configFingerprint": master_config_fingerprint(config),
        "snapshot": refreshed,
    })
    return refreshed, False


def inspect(args: argparse.Namespace) -> dict:
    workspace = Path(args.workspace).resolve()
    requested_dir = resolve_workspace_path(workspace, args.output_dir)
    cache_path = resolve_workspace_path(workspace, getattr(args, "master_cache", ".cnc-cache/master-snapshot.json"))
    cache_ttl = int(getattr(args, "master_cache_ttl", 300))
    requested_dir.mkdir(parents=True, exist_ok=True)
    output_dir = requested_dir / f"run-{uuid.uuid4().hex[:8]}" if any(requested_dir.iterdir()) else requested_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    master_config = master_data_snapshot.load(args.master_config)
    package_config = sp_cnc_package_ops.read_json(args.package_config)
    package_template = sp_cnc_package_ops.read_json(args.package_template)
    with ThreadPoolExecutor(max_workers=3) as executor:
        scan_future = executor.submit(local_file_pipeline.scan_folder, args.source)
        master_future = executor.submit(load_or_refresh_masters, master_config, cache_path, cache_ttl)
        package_future = executor.submit(sp_cnc_package_ops.preview, package_config, package_template, args.package)
        scan = scan_future.result()
        masters, master_cache_hit = master_future.result()
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
            "cacheHit": master_cache_hit,
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


def master_sets(snapshot: dict) -> dict:
    mapping = {"DuAn": "projects", "GoiThau": "packages", "PhapNhan": "legalEntities", "NhaThau": "contractors"}
    return {field: {item["code"] for item in snapshot.get("lists", {}).get(category, {}).get("items", [])} for field, category in mapping.items()}


BUSINESS_FIELD_ALIASES = {
    "project": "DuAn",
    "projectcode": "DuAn",
    "package": "DestinationPackage",
    "packagefolder": "DestinationPackage",
    "destinationpackage": "DestinationPackage",
    "packagecode": "GoiThau",
    "tenderpackage": "GoiThau",
    "tenderpackagecode": "GoiThau",
    "legalentity": "PhapNhan",
    "legalentitycode": "PhapNhan",
    "contractor": "NhaThau",
    "contractorcode": "NhaThau",
    "contractparty": "NhaThau",
    "contractnumber": "ContractSequence",
    "contractsequence": "ContractSequence",
    "paymentsequence": "DocumentSequence",
    "documentsequence": "DocumentSequence",
    "parentcontractcode": "ParentContractCode",
    "expirydate": "ExpiryDateYYMMDD",
    "expirydateyymmdd": "ExpiryDateYYMMDD",
}
CANONICAL_BUSINESS_FIELDS = {
    "DuAn", "LoaiTaiLieu", "GoiThau", "PhapNhan", "NhaThau", "ParentContractCode",
    "ContractSequence", "DocumentSequence", "ExpiryDateYYMMDD", "DestinationPackage",
}


def canonical_business_field(field: str) -> str:
    stripped = field.strip()
    if stripped in CANONICAL_BUSINESS_FIELDS:
        return stripped
    alias = BUSINESS_FIELD_ALIASES.get(re.sub(r"[^a-z0-9]", "", stripped.casefold()))
    if alias:
        return alias
    raise RuntimeError(f"Unsupported business field: {field}")


def resolve_master_value(snapshot: dict, field: str, value: str) -> dict:
    mapping = {"DuAn": "projects", "GoiThau": "packages", "PhapNhan": "legalEntities", "NhaThau": "contractors"}
    category = mapping[field]
    items = snapshot.get("lists", {}).get(category, {}).get("items", [])
    query = search_text(value)
    exact = [item for item in items if search_text(item.get("code", "")) == query or search_text(item.get("name", "")) == query]
    related = [item for item in items if query and (query in search_text(item.get("name", "")) or search_text(item.get("name", "")) in query)]
    matches = exact or related
    unique = {str(item.get("code", "")).strip().upper(): item for item in matches if item.get("code")}
    if len(unique) == 1:
        return {"status": "resolved", "code": next(iter(unique)), "candidates": list(unique.values())}
    return {"status": "not_found" if not unique else "ambiguous", "code": None, "candidates": list(unique.values())}


def validate_business_values(values: dict, snapshot: dict) -> tuple[dict, list[dict]]:
    prepared = dict(values)
    issues = []
    for field in ("DuAn", "GoiThau", "PhapNhan", "NhaThau"):
        if not prepared.get(field):
            continue
        resolution = resolve_master_value(snapshot, field, prepared[field])
        if resolution["status"] == "resolved":
            prepared[field] = resolution["code"]
        else:
            issues.append({"field": field, **resolution})
    return prepared, issues


def infer_master_values_from_request(values: dict, request_context: str, snapshot: dict) -> dict:
    prepared = dict(values)
    normalized = search_text(request_context)
    mapping = {"DuAn": "projects", "GoiThau": "packages", "PhapNhan": "legalEntities", "NhaThau": "contractors"}
    for field, category in mapping.items():
        if prepared.get(field):
            continue
        matches = set()
        for item in snapshot.get("lists", {}).get(category, {}).get("items", []):
            code = str(item.get("code", "")).strip().upper()
            if code and re.search(rf"(?<![a-z0-9]){re.escape(search_text(code))}(?![a-z0-9])", normalized):
                matches.add(code)
        if len(matches) == 1:
            prepared[field] = next(iter(matches))
    if not prepared.get("ContractSequence"):
        contract_matches = set(re.findall(r"\b(?:hop\s+dong|hd)\s*(?:so\s*)?(\d{1,2})\b", normalized))
        if len(contract_matches) == 1:
            prepared["ContractSequence"] = next(iter(contract_matches))
    return prepared


def values_for_rule(values: dict, rule: dict) -> tuple[dict, list[str]]:
    allowed = set(rule.get("requiredForCode", []))
    allowed.update(field for field, policy in rule.get("metadataPolicy", {}).items() if policy == "optional_input")
    if rule.get("mode") == "parent_contract":
        allowed.update(("DuAn", "PhapNhan", "NhaThau", "ContractSequence"))
    filtered = {field: value for field, value in values.items() if field in allowed}
    ignored = [field for field in values if field not in allowed]
    return filtered, ignored


def separate_destination_package(values: dict, expected_package: str) -> tuple[dict, list[str]]:
    prepared = dict(values)
    destination = prepared.pop("DestinationPackage", None)
    if destination is None:
        return prepared, []
    if str(destination).strip().casefold() != str(expected_package).strip().casefold():
        raise RuntimeError("Destination package conflicts with --package")
    return prepared, ["DestinationPackage"]


def parse_values(values: list[str]) -> dict:
    result = {}
    for value in values:
        if "=" not in value:
            raise RuntimeError(f"Invalid code value: {value}")
        key, item = value.split("=", 1)
        if not key.strip() or not item.strip():
            raise RuntimeError(f"Invalid code value: {value}")
        canonical = canonical_business_field(key)
        normalized_value = item.strip()
        if canonical in {"ContractSequence", "DocumentSequence"}:
            inferred = infer_sequence_value(normalized_value, canonical)
            if inferred:
                normalized_value = inferred
        if canonical in result and result[canonical] != normalized_value:
            raise RuntimeError(f"Conflicting values for {canonical}")
        result[canonical] = normalized_value
    return result


def search_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value).casefold()).replace("đ", "d")
    return " ".join("".join(ch for ch in text if unicodedata.category(ch) != "Mn").split())


def infer_document_sequence(text: str) -> str | None:
    normalized = search_text(text)
    patterns = (
        r"\b(?:dot|lan|ky)\s*(?:thu\s*)?(\d{1,2})\b",
        r"\b(?:dot|lan|ky)\s+(?:thanh\s+toan\s+)?(?:so\s+)?(\d{1,2})\b",
    )
    matches = {match.group(1) for pattern in patterns for match in re.finditer(pattern, normalized)}
    if len(matches) != 1:
        return None
    return next(iter(matches))


def infer_sequence_value(text: str, field: str) -> str | None:
    stripped = str(text).strip()
    if stripped.isdigit() and 1 <= len(stripped) <= 2:
        return stripped
    if field == "ContractSequence":
        normalized = search_text(stripped)
        matches = set(re.findall(r"\b(?:hop\s+dong|hd)\s*(?:so\s*)?(\d{1,2})\b", normalized))
        return next(iter(matches)) if len(matches) == 1 else None
    return infer_document_sequence(stripped)


def prepare_business_values(values: dict, request_context: str, matrix: dict) -> dict:
    prepared = dict(values)
    if not prepared.get("DocumentSequence"):
        inferred = infer_document_sequence(request_context)
        if inferred:
            prepared["DocumentSequence"] = inferred
    parent_fields = ("DuAn", "PhapNhan", "NhaThau", "ContractSequence")
    if not prepared.get("ParentContractCode") and all(prepared.get(field) for field in parent_fields):
        parent = document_code_engine.generate("CTR", prepared, matrix)
        if parent["status"] == "ready":
            prepared["ParentContractCode"] = parent["DocumentCode"]
    return prepared


def missing_business_question(missing_fields: list[str], values: dict) -> str:
    if "ParentContractCode" in missing_fields:
        missing_parts = [
            label for field, label in (
                ("DuAn", "dự án"),
                ("PhapNhan", "pháp nhân"),
                ("NhaThau", "nhà thầu"),
                ("ContractSequence", "số thứ tự hợp đồng"),
            ) if not values.get(field)
        ]
        if missing_parts:
            return "Cần bổ sung " + ", ".join(missing_parts) + " để xác định hợp đồng của hồ sơ."
        return "Cần xác định hợp đồng áp dụng cho hồ sơ."
    if "DocumentSequence" in missing_fields:
        return "Cần xác định đợt, lần hoặc kỳ của hồ sơ."
    return "Cần bổ sung thông tin nghiệp vụ còn thiếu để tạo mã."


def master_issue_question(issue: dict) -> str:
    labels = {"DuAn": "dự án", "GoiThau": "gói thầu", "PhapNhan": "pháp nhân", "NhaThau": "nhà thầu"}
    label = labels[issue["field"]]
    if issue["status"] == "ambiguous":
        return f"Có nhiều {label} phù hợp; cần chọn đúng giá trị trước khi tạo mã."
    return f"Không tìm thấy {label} phù hợp trong master data đang hoạt động."


def preview_markdown(plan: dict, collisions: dict) -> str:
    collision_paths = {item["sourceRelativePath"] for item in collisions.get("collisions", [])}
    rows = ["| File nguồn | Mã tài liệu | Tên file sau upload | SharePoint path | Collision |", "|---|---|---|---|---|"]
    for item in plan.get("files", []):
        if item.get("state") != "ready":
            continue
        source = item["sourceRelativePath"]
        rows.append(f"| {source} | {item['DocumentCode']} | {item['newFileName']} | {item['destinationRelativePath']} | {'Có' if source in collision_paths else 'Không'} |")
    return "\n".join(rows)


def plan_batch(args: argparse.Namespace) -> dict:
    context_path = Path(args.context).resolve()
    context = local_file_pipeline._read(context_path)
    scan = local_file_pipeline._read(context["scanPath"])
    if not scan.get("files"):
        return {
            "status": "blocked",
            "reason": "NO_SOURCE_FILES",
            "fileCount": 0,
            "message": "Không có file hợp lệ trong thư mục nguồn để lập preview.",
        }
    snapshot = local_file_pipeline._read(context["masterData"]["snapshotPath"])
    base = Path(__file__).parents[1]
    matrix = document_code_engine.load_matrix(base / "config/document-code-matrix.json")
    aliases = document_code_engine.load_matrix(base / "config/classification-aliases.json")
    document_type = document_code_engine.resolve_document_type(args.document_type, matrix, aliases)
    if document_type is None:
        raise RuntimeError(f"Document type is ambiguous or unsupported: {args.document_type}")
    rule = matrix["rules"][document_type]
    request_context = " ".join(filter(None, (args.document_type, getattr(args, "request_context", ""))))
    supplied_values, destination_ignored = separate_destination_package(
        parse_values(args.value), context["package"]["packageFolderName"]
    )
    supplied_values = infer_master_values_from_request(supplied_values, request_context, snapshot)
    supplied_values, rule_ignored = values_for_rule(supplied_values, rule)
    ignored_fields = destination_ignored + rule_ignored
    values, master_issues = validate_business_values(supplied_values, snapshot)
    if master_issues:
        issue = master_issues[0]
        return {
            "status": "needs_user_input",
            "documentTypeCode": document_type,
            "fileCount": len(scan.get("files", [])),
            "question": master_issue_question(issue),
            "masterIssue": issue,
        }
    values = prepare_business_values(
        values,
        request_context,
        matrix,
    )
    if values.get("ParentContractCode"):
        parent = document_code_engine.parse_contract_code(values["ParentContractCode"], matrix)
        parent_values, parent_issues = validate_business_values(parent, snapshot)
        if parent_issues:
            issue = parent_issues[0]
            return {
                "status": "needs_user_input",
                "documentTypeCode": document_type,
                "fileCount": len(scan.get("files", [])),
                "question": master_issue_question(issue),
                "masterIssue": issue,
            }
        conflicts = [
            field for field in ("DuAn", "PhapNhan", "NhaThau", "ContractSequence")
            if values.get(field) and str(values[field]).strip().upper().zfill(2 if field == "ContractSequence" else 0)
            != str(parent_values[field]).strip().upper()
        ]
        if conflicts:
            return {
                "status": "needs_user_input",
                "documentTypeCode": document_type,
                "fileCount": len(scan.get("files", [])),
                "question": "Thông tin hợp đồng đang mâu thuẫn; cần xác nhận lại trước khi tạo mã.",
                "conflictingFields": conflicts,
            }
        values["ParentContractCode"] = document_code_engine.generate("CTR", parent_values, matrix)["DocumentCode"]
    items = [{"id": item["relativePath"], "documentTypeCode": document_type, "values": values} for item in scan.get("files", [])]
    code_input = {"items": items}
    codes = document_code_engine.generate_payload(code_input, matrix)
    incomplete = [result for result in codes.get("results", {}).values() if result.get("status") != "ready"]
    if incomplete:
        invalid = [result for result in incomplete if result.get("status") != "needs_user_input"]
        if invalid:
            errors = list(dict.fromkeys(error for result in invalid for error in result.get("errors", [])))
            return {
                "status": "invalid",
                "reason": "CODE_GENERATION_INVALID",
                "documentTypeCode": document_type,
                "fileCount": len(items),
                "errors": errors,
                "message": "Thông tin đã có nhưng không hợp lệ để tạo mã; cần sửa dữ liệu đầu vào trước khi lập preview.",
                "resolvedValues": values,
                "ignoredFields": ignored_fields,
            }
        missing = list(dict.fromkeys(field for result in incomplete for field in result.get("missingFields", [])))
        return {
            "status": "needs_user_input",
            "documentTypeCode": document_type,
            "fileCount": len(items),
            "missingFields": missing,
            "question": missing_business_question(missing, values),
            "resolvedValues": values,
            "ignoredFields": ignored_fields,
        }
    masters = master_sets(snapshot)
    for relative_path, result in codes.get("results", {}).items():
        detected = document_code_engine.detect_existing_prefix(relative_path, matrix, masters)
        result["fileNameDecision"] = {
            "status": "agent_decided" if detected["status"] in {"unique_match", "no_prefix"} else "needs_user_input",
            "oldPrefixToRemove": detected.get("prefix"),
            "cleanBaseName": detected.get("cleanBaseName", Path(relative_path).stem),
        }
    routing = local_file_pipeline._read(base / "config/folder-routing.json")["routingByDocumentType"]
    package = context["package"]["packageFolderName"]
    plan = local_file_pipeline.build_plan(scan, codes["results"], routing, package)
    unresolved_files = [item for item in plan.get("files", []) if item.get("state") != "ready"]
    if unresolved_files:
        write_json(context_path.parent / "plan.json", plan)
        return {
            "status": "needs_user_input",
            "documentTypeCode": document_type,
            "fileCount": len(items),
            "unresolvedFileCount": len(unresolved_files),
            "question": "Có file chưa xác định được tên hoặc thư mục đích; cần kiểm tra trước khi lập preview.",
            "unresolvedFiles": [item["sourceRelativePath"] for item in unresolved_files],
            "ignoredFields": ignored_fields,
            "uploadPlanPath": str(context_path.parent / "plan.json"),
        }
    upload_config = sp_cnc_upload_ops.load_config(base / "config/sharepoint.json")
    collisions = sp_cnc_upload_ops.check_collisions(upload_config, plan)
    if not collisions["ok"]:
        plan["state"] = "blocked"
    output_dir = context_path.parent
    paths = {
        "codeInputPath": output_dir / "code-input.json",
        "codesPath": output_dir / "codes.json",
        "uploadPlanPath": output_dir / "plan.json",
        "collisionPath": output_dir / "collision-check.json",
        "previewPath": output_dir / "preview.md",
    }
    write_json(paths["codeInputPath"], code_input)
    write_json(paths["codesPath"], codes)
    write_json(paths["uploadPlanPath"], plan)
    write_json(paths["collisionPath"], collisions)
    markdown = preview_markdown(plan, collisions)
    if markdown.count("\n") - 1 != len(items):
        raise RuntimeError("Preview does not include every source file")
    paths["previewPath"].write_text(markdown, encoding="utf-8")
    return {
        "status": "ready" if plan["state"] == "planned" else "blocked",
        "documentTypeCode": document_type,
        "fileCount": len(items),
        "collisionCount": len(collisions["collisions"]),
        "ignoredFields": ignored_fields,
        "previewMarkdown": markdown,
        **{key: str(value) for key, value in paths.items()},
        "packagePlanPath": context["package"]["planPath"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    base = Path(__file__).parents[1]
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--source", required=True)
    inspect_parser.add_argument("--package", required=True)
    inspect_parser.add_argument("--workspace", required=True)
    inspect_parser.add_argument("--output-dir", default=".cnc-work")
    inspect_parser.add_argument("--master-cache", default=".cnc-cache/master-snapshot.json")
    inspect_parser.add_argument("--master-cache-ttl", type=int, default=300)
    inspect_parser.add_argument("--master-config", default=str(base / "config/master-data.json"))
    inspect_parser.add_argument("--package-config", default=str(base / "config/package-sharepoint.json"))
    inspect_parser.add_argument("--package-template", default=str(base / "config/package-folder-template.json"))
    plan_parser = commands.add_parser("plan-batch")
    plan_parser.add_argument("--context", required=True)
    plan_parser.add_argument("--document-type", required=True)
    plan_parser.add_argument("--request-context", default="")
    plan_parser.add_argument("--value", action="append", default=[])
    combined_parser = commands.add_parser("prepare-and-plan")
    combined_parser.add_argument("--source", required=True)
    combined_parser.add_argument("--package", required=True)
    combined_parser.add_argument("--workspace", required=True)
    combined_parser.add_argument("--output-dir", default=".cnc-work")
    combined_parser.add_argument("--master-cache", default=".cnc-cache/master-snapshot.json")
    combined_parser.add_argument("--master-cache-ttl", type=int, default=300)
    combined_parser.add_argument("--master-config", default=str(base / "config/master-data.json"))
    combined_parser.add_argument("--package-config", default=str(base / "config/package-sharepoint.json"))
    combined_parser.add_argument("--package-template", default=str(base / "config/package-folder-template.json"))
    combined_parser.add_argument("--document-type", required=True)
    combined_parser.add_argument("--request-context", default="")
    combined_parser.add_argument("--value", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            result = inspect(args)
            output = {
                "status": "ready", "fileCount": len(result["files"]), "masterCounts": result["masterData"]["counts"],
                "package": result["package"]["packageFolderName"], "packageVerified": result["package"]["verified"],
                "missingFolderCount": len(result["package"]["missing"]), "contextPath": str(Path(result["scanPath"]).parent / "prepare-context.json"),
                "masterSnapshotPath": result["masterData"]["snapshotPath"],
                "masterCacheHit": result["masterData"]["cacheHit"],
            }
        elif args.command == "prepare-and-plan":
            prepared = inspect(args)
            context_path = str(Path(prepared["scanPath"]).parent / "prepare-context.json")
            plan_args = argparse.Namespace(
                context=context_path,
                document_type=args.document_type,
                request_context=args.request_context,
                value=args.value,
            )
            output = plan_batch(plan_args)
            output["contextPath"] = context_path
            output["masterCacheHit"] = prepared["masterData"]["cacheHit"]
        else:
            output = plan_batch(args)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
