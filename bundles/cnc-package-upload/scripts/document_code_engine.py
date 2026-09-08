#!/usr/bin/env python3
"""Deterministic CNC document-code renderer and parser.

Input JSON example:
{"documentTypeCode":"FAC","values":{"ParentContractCode":"M01_TTDN_CTC_CTR_01"}}

Batch input example:
{"items":[{"id":"file-a.pdf","documentTypeCode":"FAC","values":{"ParentContractCode":"M01_TTDN_CTC_CTR_01"}}]}
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

META_FIELDS = ("DuAn", "LoaiTaiLieu", "GoiThau", "PhapNhan", "NhaThau")
PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}|\[[^\[\]]+\]")
CODE_TOKEN_RE = re.compile(r"^[A-Z0-9]+$")

class CodeEngineError(ValueError):
    pass

def load_matrix(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def _search_key(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value).casefold()).replace("đ", "d")
    return " ".join("".join(ch for ch in text if unicodedata.category(ch) != "Mn").split())

def resolve_document_type(query: str, matrix: dict, aliases: dict) -> str | None:
    key = _search_key(query)
    matches = []
    for code, rule in matrix.get("rules", {}).items():
        terms = [code, rule.get("businessName", ""), *aliases.get("aliases", {}).get(code, [])]
        if any(_search_key(term) == key for term in terms):
            matches.append(code)
    return matches[0] if len(matches) == 1 else None

def normalize_code_token(value, field: str) -> str:
    if value is None:
        raise CodeEngineError(f"Missing {field}")
    text = str(value).strip().upper()
    if not text or not CODE_TOKEN_RE.fullmatch(text):
        raise CodeEngineError(f"Invalid {field}: {value!r}")
    return text

def normalize_sequence(value, field: str, width: int = 2) -> str:
    if value is None or str(value).strip() == "":
        raise CodeEngineError(f"Missing {field}")
    text = str(value).strip()
    if not text.isdigit():
        raise CodeEngineError(f"Invalid {field}: {value!r}")
    if len(text) > width:
        raise CodeEngineError(f"{field} exceeds {width} digits")
    return text.zfill(width)

def normalize_expiry(value) -> str:
    if value is None:
        raise CodeEngineError("Missing ExpiryDateYYMMDD")
    text = re.sub(r"\D", "", str(value))
    if len(text) != 6:
        raise CodeEngineError("ExpiryDateYYMMDD must contain exactly 6 digits")
    return text

def parse_contract_code(code: str, matrix: dict) -> dict:
    text = str(code).strip().upper()
    match = re.fullmatch(matrix["parentCode"]["regex"], text)
    if not match:
        raise CodeEngineError(f"Invalid ParentContractCode: {code!r}")
    result = match.groupdict()
    result["ParentContractCode"] = text
    return result

def _prepare_value(field: str, value, matrix: dict) -> str:
    if field in ("ContractSequence", "DocumentSequence"):
        return normalize_sequence(value, field, matrix["normalization"]["sequenceWidth"])
    if field == "ExpiryDateYYMMDD":
        return normalize_expiry(value)
    if field == "ParentContractCode":
        return parse_contract_code(value, matrix)["ParentContractCode"]
    return normalize_code_token(value, field)

def _render(pattern: str, values: dict) -> str:
    try:
        code = pattern.format(**values)
    except KeyError as exc:
        raise CodeEngineError(f"Missing {exc.args[0]}") from exc
    if PLACEHOLDER_RE.search(code):
        raise CodeEngineError("Rendered code still contains placeholder")
    if "__" in code or code.startswith("_") or code.endswith("_"):
        raise CodeEngineError("Rendered code has empty token")
    return code

def derive_metadata(rule: dict, code: str, values: dict, matrix: dict) -> dict:
    policy = rule["metadataPolicy"]
    parent = None
    if rule["mode"] == "parent_contract":
        parent = parse_contract_code(values["ParentContractCode"], matrix)
    result = {}
    for field in META_FIELDS:
        action = policy[field]
        if action == "null":
            result[field] = None
        elif action == "derive_from_parent":
            result[field] = parent.get(field)
        elif action == "derive_from_code":
            result[field] = values.get(field)
        elif action == "optional_input":
            result[field] = normalize_code_token(values[field], field) if values.get(field) not in (None, "") else None
        elif action.startswith("constant:"):
            result[field] = action.split(":", 1)[1]
        else:
            raise CodeEngineError(f"Unknown metadata policy {action!r}")
    return result

def generate(document_type: str, values: dict, matrix: dict) -> dict:
    requested = normalize_code_token(document_type, "documentTypeCode")
    canonical = matrix.get("documentTypeAliases", {}).get(requested, requested)
    rule = matrix["rules"].get(canonical)
    if not rule:
        return {"status": "unsupported", "documentTypeCode": canonical, "DocumentCode": None,
                "missingFields": [], "errors": ["No executable rule in HoSo matrix"]}

    prepared = dict(values or {})
    prepared["LoaiTaiLieu"] = canonical
    missing = [f for f in rule["requiredForCode"] if prepared.get(f) in (None, "")]
    if missing:
        return {"status": "needs_user_input", "documentTypeCode": canonical, "DocumentCode": None,
                "missingFields": missing, "errors": []}
    try:
        for field in rule["requiredForCode"]:
            prepared[field] = _prepare_value(field, prepared[field], matrix)
        code = _render(rule["codePattern"], prepared)
        metadata = derive_metadata(rule, code, prepared, matrix)
        validation = validate_result(rule, code, metadata, prepared, matrix)
        if not validation["valid"]:
            return {"status": "invalid", "documentTypeCode": canonical, "DocumentCode": None,
                    "missingFields": [], "errors": validation["errors"], "validation": validation}
        return {
            "status": "ready",
            "documentTypeCode": canonical,
            "ruleId": canonical,
            "codePattern": rule["codePattern"],
            "DocumentCode": code,
            "components": metadata,
            "runtimeFields": {k: prepared[k] for k in rule["requiredForCode"] if k not in META_FIELDS and k != "ParentContractCode"},
            "inheritedFields": {"ParentContractCode": prepared["ParentContractCode"]} if "ParentContractCode" in prepared else {},
            "missingFields": [],
            "errors": [],
            "validation": validation,
        }
    except CodeEngineError as exc:
        return {"status": "invalid", "documentTypeCode": canonical, "DocumentCode": None,
                "missingFields": [], "errors": [str(exc)]}

def generate_payload(payload: dict, matrix: dict) -> dict:
    if isinstance(payload, list):
        payload = {"items": payload}
    items = payload.get("items")
    if items is None:
        return generate(payload["documentTypeCode"], payload.get("values", {}), matrix)
    if not isinstance(items, list):
        raise CodeEngineError("items must be an array")
    results = {}
    counts = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise CodeEngineError(f"items[{index}] must be an object")
        item_id = str(item.get("id") or f"item-{index + 1}").strip()
        if item_id in results:
            raise CodeEngineError(f"Duplicate batch item id: {item_id}")
        result = generate(item["documentTypeCode"], item.get("values", item.get("metadata", {})), matrix)
        results[item_id] = result
        status = result["status"]
        counts[status] = counts.get(status, 0) + 1
    return {"status": "batch", "results": results, "summary": {"total": len(items), **counts}}

def validate_result(rule: dict, code: str, metadata: dict, values: dict, matrix: dict) -> dict:
    errors = []
    if PLACEHOLDER_RE.search(code): errors.append("placeholder remains")
    if "__" in code: errors.append("empty code token")
    if rule["mode"] == "parent_contract" and not code.startswith(values["ParentContractCode"] + "_"):
        errors.append("child code does not preserve parent contract code")
    if metadata.get("LoaiTaiLieu") != rule["documentTypeCode"]:
        errors.append("LoaiTaiLieu does not match rule")
    return {"valid": not errors, "errors": errors, "patternMatched": not errors}

def _master_contains(master_snapshot: dict, field: str, value: str) -> bool:
    allowed = master_snapshot.get(field)
    return allowed is None or value in {str(x).strip().upper() for x in allowed}

def _match_direct_tokens(tokens: list[str], rule_id: str, rule: dict, matrix: dict, masters: dict):
    pattern_fields = re.findall(r"\{(\w+)\}", rule["codePattern"])
    literal_tokens = [x for x in rule["codePattern"].split("_") if not x.startswith("{")]
    pattern_parts = rule["codePattern"].split("_")
    if len(tokens) != len(pattern_parts): return None
    values = {}
    for token, part in zip(tokens, pattern_parts):
        if part.startswith("{"):
            field = part[1:-1]
            try: values[field] = _prepare_value(field, token, matrix)
            except CodeEngineError: return None
        elif token != part: return None
    values["LoaiTaiLieu"] = rule_id
    try:
        rendered = _render(rule["codePattern"], values)
        metadata = derive_metadata(rule, rendered, values, matrix)
    except CodeEngineError:
        return None
    for field in ("DuAn", "GoiThau", "PhapNhan", "NhaThau"):
        value = metadata.get(field)
        if value and not _master_contains(masters, field, value): return None
    return {"ruleId": rule_id, "prefix": rendered, "components": metadata}

def validate_existing_code(candidate: str, matrix: dict, master_snapshot: dict) -> list[dict]:
    text = str(candidate).strip().upper()
    matches = []
    # Direct rules.
    for rule_id, rule in matrix["rules"].items():
        if rule["mode"] != "direct": continue
        match = _match_direct_tokens(text.split("_"), rule_id, rule, matrix, master_snapshot)
        if match: matches.append(match)
    # Parent-contract child rules: identify the valid parent boundary, then verify exact suffix.
    parts = text.split("_")
    if len(parts) >= 6:
        for boundary in range(5, len(parts)):
            parent_text = "_".join(parts[:boundary])
            try: parent = parse_contract_code(parent_text, matrix)
            except CodeEngineError: continue
            if not all(_master_contains(master_snapshot, f, parent[f]) for f in ("DuAn", "PhapNhan", "NhaThau")):
                continue
            suffix = parts[boundary:]
            for rule_id, rule in matrix["rules"].items():
                if rule["mode"] != "parent_contract": continue
                values = {"ParentContractCode": parent_text}
                expected_fields = rule["requiredForCode"][1:]
                if len(suffix) != 1 + len(expected_fields) or suffix[0] != rule_id: continue
                ok = True
                for field, token in zip(expected_fields, suffix[1:]):
                    try: values[field] = _prepare_value(field, token, matrix)
                    except CodeEngineError: ok = False; break
                if not ok: continue
                try:
                    rendered = _render(rule["codePattern"], values)
                    metadata = derive_metadata(rule, rendered, values, matrix)
                except CodeEngineError: continue
                matches.append({"ruleId":rule_id,"prefix":rendered,"components":metadata})
    unique = {(m["ruleId"], m["prefix"]):m for m in matches}
    return list(unique.values())

def detect_existing_prefix(filename: str, matrix: dict, master_snapshot: dict) -> dict:
    stem = Path(filename).stem
    # Candidate boundaries occur only at an underscore followed by remaining content.
    candidates = []
    for idx, ch in enumerate(stem):
        if ch != "_" or idx == 0 or idx == len(stem)-1: continue
        candidate = stem[:idx]
        rest = stem[idx+1:]
        for match in validate_existing_code(candidate, matrix, master_snapshot):
            candidates.append({**match, "cleanBaseName":rest})
    unique = {(x["ruleId"],x["prefix"],x["cleanBaseName"]):x for x in candidates}
    found = list(unique.values())
    if not found:
        return {"status":"no_prefix","prefix":None,"ruleId":None,"cleanBaseName":stem,"candidates":[]}
    # Prefer longest valid code boundary. Equal-length alternatives are ambiguous.
    max_len=max(len(x["prefix"]) for x in found); best=[x for x in found if len(x["prefix"])==max_len]
    if len(best) != 1:
        return {"status":"ambiguous","prefix":None,"ruleId":None,"cleanBaseName":stem,"candidates":best}
    return {"status":"unique_match",**best[0],"candidates":found}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", default=str(Path(__file__).parents[1] / "config" / "document-code-matrix.json"))
    parser.add_argument("--input", help="JSON object; reads stdin when omitted")
    parser.add_argument("--input-file", help="UTF-8 JSON input file; avoids command-line quoting for batches")
    parser.add_argument("--output", help="Write UTF-8 JSON output instead of stdout")
    parser.add_argument("--describe-type", help="Return one rule's required inputs without generating a code")
    parser.add_argument("--aliases", default=str(Path(__file__).parents[1] / "config" / "classification-aliases.json"))
    args = parser.parse_args()
    if args.input and args.input_file:
        parser.error("--input and --input-file are mutually exclusive")
    matrix = load_matrix(args.matrix)
    if args.describe_type:
        resolved = resolve_document_type(args.describe_type, matrix, load_matrix(args.aliases))
        code = resolved or matrix.get("documentTypeAliases", {}).get(args.describe_type.upper(), args.describe_type.upper())
        rule = matrix.get("rules", {}).get(code)
        result = {"status": "ready", "documentTypeCode": code, "requiredForCode": rule["requiredForCode"], "codePattern": rule["codePattern"]} if rule else {"status": "unsupported", "documentTypeCode": code}
    else:
        if args.input_file:
            payload = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
        else:
            payload = json.loads(args.input) if args.input else json.load(sys.stdin)
        result = generate_payload(payload, matrix)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    if result["status"] == "batch":
        return 0 if not any(item["status"] == "invalid" for item in result["results"].values()) else 2
    return 0 if result["status"] in {"ready", "needs_user_input", "unsupported"} else 2

if __name__ == "__main__":
    raise SystemExit(main())
