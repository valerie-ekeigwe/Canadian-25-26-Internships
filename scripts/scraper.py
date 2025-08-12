# scripts/scraper.py
from __future__ import annotations
import argparse, json, re, time
from typing import Any, Dict, List
from pathlib import Path

import requests
import yaml

INTERN_RE = re.compile(r"\b(intern(ship)?|co[- ]?op|coop|student|summer|placement)\b", re.I)

def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def is_internish(text: str) -> bool:
    return bool(INTERN_RE.search(text or ""))

def looks_canadian(loc: str | None) -> bool:
    if not loc:
        return False
    t = f" {loc.lower()} "
    if " canada " in t:
        return True
    hints = [
        " toronto "," ontario "," on "," ottawa "," waterloo "," montreal ",
        " québec "," quebec "," qc "," vancouver "," british columbia "," bc ",
        " calgary "," edmonton "," alberta "," ab "," manitoba "," mb "," winnipeg ",
        " saskatchewan "," sk "," regina "," saskatoon "," nova scotia "," ns "," halifax ",
        " new brunswick "," nb "," pei "," prince edward island "," newfoundland "," nl ",
        " st. john’s "," st johns "," yukon "," whitehorse "," northwest territories "," nt ",
        " nunavut "," nu "
    ]
    return any(h in t for h in hints)

def gh_fetch(board: str) -> List[Dict[str, Any]]:
    # Greenhouse board: https://api.greenhouse.io/v1/boards/{board}/jobs
    url = f"https://api.greenhouse.io/v1/boards/{board}/jobs"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json() or {}
    return data.get("jobs", [])

def gh_to_posting(j: Dict[str, Any], company_label: str) -> Dict[str, Any]:
    title = j.get("title") or ""
    # locations array or single
    loc = None
    locs = j.get("location")
    if isinstance(locs, dict):
        loc = locs.get("name")
    elif isinstance(locs, list) and locs:
        loc = locs[0].get("name")
    apply_url = j.get("absolute_url") or j.get("url") or j.get("internal_job_id")
    return {
        "company": company_label,
        "role": title,
        "location": loc,
        "country": "Canada" if looks_canadian(loc) else None,
        "deadline": None,
        "status": "Open",
        "tags": [],
        "url": apply_url,
        "level": None,
    }

def lever_fetch(company_slug: str) -> List[Dict[str, Any]]:
    # Lever: https://api.lever.co/v0/postings/{company}?mode=json
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json() or []

def lever_to_posting(j: Dict[str, Any], company_label: str) -> Dict[str, Any]:
    title = j.get("text") or j.get("title") or ""
    # locations is list of dicts with 'name'
    loc = None
    if j.get("categories"):
        loc = j["categories"].get("location")
    if not loc:
        locs = j.get("workTypes") or j.get("locations") or []
        if isinstance(locs, list) and locs:
            cand = locs[0]
            if isinstance(cand, dict):
                loc = cand.get("name")
            elif isinstance(cand, str):
                loc = cand
    apply_url = j.get("hostedUrl") or j.get("applyUrl") or j.get("url")
    return {
        "company": company_label,
        "role": title,
        "location": loc,
        "country": "Canada" if looks_canadian(loc) else None,
        "deadline": None,
        "status": "Open",
        "tags": [],
        "url": apply_url,
        "level": None,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filters", default="filters.yaml")
    ap.add_argument("--output", default="data/postings.json")
    ap.add_argument("--input", default=None, help="Optional: existing postings to merge in")
    args = ap.parse_args()

    cfg = load_yaml(args.filters)

    postings: List[Dict[str, Any]] = []

    # Pull from Greenhouse boards
    for ent in (cfg.get("greenhouse") or []):
        name = ent.get("name")
        board = ent.get("board")
        if not board or not name:
            continue
        # Expect format: https://api.greenhouse.io/v1/boards/{board}
        board_slug = board.rstrip("/").split("/")[-1]
        try:
            jobs = gh_fetch(board_slug)
            for j in jobs:
                p = gh_to_posting(j, name)
                if p["location"] and looks_canadian(p["location"]) and is_internish(p["role"]):
                    postings.append(p)
        except Exception:
            # Keep going even if a board fails
            continue
        time.sleep(0.3)

    # Pull from Lever boards
    for ent in (cfg.get("lever") or []):
        name = ent.get("name")
        board = ent.get("board")
        if not board or not name:
            continue
        # jobs.lever.co/{slug}
        slug = board.rstrip("/").split("/")[-1]
        try:
            jobs = lever_fetch(slug)
            for j in jobs:
                p = lever_to_posting(j, name)
                if p["location"] and looks_canadian(p["location"]) and is_internish(p["role"]):
                    postings.append(p)
        except Exception:
            continue
        time.sleep(0.3)

    # Merge optional existing postings (e.g., your manual law/OEM entries)
    if args.input:
        pth = Path(args.input)
        if pth.exists():
            existing = json.loads(pth.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and "items" in existing:
                existing = list(existing["items"].values())
            if isinstance(existing, list):
                for r in existing:
                    title = r.get("role") or r.get("title") or ""
                    loc = r.get("location")
                    if looks_canadian(loc) and is_internish(title):
                        postings.append({
                            "company": r.get("company") or "Unknown",
                            "role": title,
                            "location": loc,
                            "country": "Canada",
                            "deadline": r.get("deadline"),
                            "status": r.get("status") or "Open",
                            "tags": r.get("tags") or [],
                            "url": r.get("url") or r.get("apply_url") or r.get("link"),
                            "level": r.get("level"),
                        })

    # De-dupe by (company, role, url)
    dedup: Dict[tuple, Dict[str, Any]] = {}
    for r in postings:
        key = (str(r.get("company","")).lower(), str(r.get("role","")).lower(), str(r.get("url","")).lower())
        dedup[key] = r
    postings = list(dedup.values())

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(postings, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[scraper] wrote {len(postings)} postings → {args.output}")

if __name__ == "__main__":
    main()
