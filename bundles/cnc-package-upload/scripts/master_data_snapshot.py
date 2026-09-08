#!/usr/bin/env python3
"""Fetch and query normalized CNC master data from configured SharePoint Lists."""
from __future__ import annotations
import argparse, json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN = Path.home() / "AppData/Roaming/ttg-os/ttg-os-home/microsoft365/delegated-token.json"

def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def norm(value): return " ".join(str(value or "").strip().split())
def get(url):
    token = load(os.environ.get("M365_TOKEN_PATH", TOKEN)).get("access_token")
    if not token: raise RuntimeError("Microsoft 365 delegated token is unavailable")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {error.read().decode('utf-8', errors='replace')}") from error
def values(url):
    out = []
    while url:
        page = get(url); out.extend(page.get("value", [])); url = page.get("@odata.nextLink")
    return out
def refresh(config):
    parsed = urllib.parse.urlparse(config["siteUrl"])
    site = get(f"{GRAPH}/sites/{parsed.netloc}:{parsed.path.rstrip('/')}")
    result = {"schemaVersion": 1, "fetchedAt": datetime.now(timezone.utc).isoformat(), "siteId": site["id"], "lists": {}}
    for key, spec in config["lists"].items():
        name = urllib.parse.quote(spec["name"])
        matches = values(f"{GRAPH}/sites/{site['id']}/lists?$filter=displayName%20eq%20'{name}'")
        if len(matches) != 1: raise RuntimeError(f"Expected one List named {spec['name']}, found {len(matches)}")
        list_id = matches[0]["id"]
        rows = {}
        for item in values(f"{GRAPH}/sites/{site['id']}/lists/{list_id}/items?$expand=fields&$top=999"):
            fields = item.get("fields", {})
            if norm(fields.get("Status")).casefold() != norm(config["activeStatus"]).casefold(): continue
            code = norm(fields.get(spec["codeField"])).upper()
            if code: rows[code] = {"code": code, "name": norm(fields.get(spec["nameField"])), "itemId": item.get("id")}
        result["lists"][key] = {"listId": list_id, "displayName": spec["name"], "items": [rows[x] for x in sorted(rows)]}
    return result
def lookup(snapshot, category, query):
    source = snapshot.get("lists", {}).get(category)
    if source is None: raise RuntimeError(f"Unknown category: {category}")
    needle = norm(query).casefold()
    matches = [row for row in source["items"] if needle in row["code"].casefold() or needle in row["name"].casefold()]
    return {"category": category, "query": query, "count": len(matches), "matches": matches}
def lookup_many(snapshot, queries):
    return {"results": {category: lookup(snapshot, category, query) for category, query in queries}}
def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("refresh"); p.add_argument("--config", required=True); p.add_argument("--output", required=True)
    p = sub.add_parser("lookup"); p.add_argument("--snapshot", required=True); p.add_argument("--category", "--kind", dest="category", required=True); p.add_argument("--query", required=True); p.add_argument("--output")
    p = sub.add_parser("lookup-many"); p.add_argument("--snapshot", required=True); p.add_argument("--query", action="append", required=True, metavar="CATEGORY=VALUE"); p.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.command == "refresh": result = refresh(load(args.config))
        elif args.command == "lookup": result = lookup(load(args.snapshot), args.category, args.query)
        else:
            queries = []
            for value in args.query:
                if "=" not in value: raise RuntimeError(f"Invalid lookup query: {value}")
                category, query = value.split("=", 1); queries.append((category, query))
            result = lookup_many(load(args.snapshot), queries)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output: Path(args.output).write_text(text, encoding="utf-8")
        else: print(text)
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False), file=sys.stderr); return 2
if __name__ == "__main__": raise SystemExit(main())
