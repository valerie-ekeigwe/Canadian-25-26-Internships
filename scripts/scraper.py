# scripts/scraper.py
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from typing import Any, List, Dict

def load_json(path: Path) -> Any:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def flatten_if_needed(data: Any) -> List[Dict[str, Any]]:
    """
    Accept:
      - list of postings -> return as-is
      - {"items": { "<url>": {...}, ... }} -> return list(items.values())
      - anything else -> empty list
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), dict):
        return list(data["items"].values())
    return []

def main():
    ap = argparse.ArgumentParser(description="Lightweight scraper passthrough/flatten step.")
    ap.add_argument("--filters", default="filters.yaml", help="(optional) filters file; not required in this step")
    ap.add_argument("--input", default="data/postings.json", help="Input JSON (array, or {items:{}})")
    ap.add_argument("--output", default="data/postings.json", help="Output flattened JSON array")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw = load_json(in_path)
    postings = flatten_if_needed(raw)

    # If input missing or unknown shape, keep empty list (normalize step can still run)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(postings, f, indent=2, ensure_ascii=False)

    print(f"[scraper] Wrote {len(postings)} rows to {out_path}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
