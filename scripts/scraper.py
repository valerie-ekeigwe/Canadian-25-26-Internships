# scripts/scraper.py
from __future__ import annotations
import os, sys, json, argparse
from typing import Any, Dict, List
import yaml
import re

# ---------------- Config helpers ----------------

def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def get_categories(filters_cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    # Support both layouts:
    #   categories: {...}
    #   filters: { categories: {...} }
    return (filters_cfg.get("categories")
            or (filters_cfg.get("filters") or {}).get("categories")
            or {})

def get_intern_markers(filters_cfg: Dict[str, Any]) -> List[str]:
    return ((filters_cfg.get("filters") or {}).get("intern_markers")
            or filters_cfg.get("intern_markers")
            or ["intern","co-op","co op","coop","student","summer","placement","industrial placement"])

# ---------------- Text helpers ----------------

CANADA_HINTS = {
    "canada"," toronto "," ontario "," on ",
    " ottawa "," waterloo "," london ",
    " montreal "," québec "," quebec "," qc ",
    " laval "," sherbrooke "," trois-rivières ",
    " vancouver "," british columbia "," bc "," burnaby "," victoria "," surrey ",
    " calgary "," edmonton "," alberta "," ab ",
    " saskatchewan "," sk "," regina "," saskatoon ",
    " manitoba "," mb "," winnipeg ",
    " new brunswick "," nb "," saint john "," moncton "," fredericton ",
    " nova scotia "," ns "," halifax ",
    " newfoundland "," nl "," st. john’s "," st johns ",
    " prince edward island "," pei "," charlottetown ",
    " yukon "," yt "," whitehorse "," northwest territories "," nt "," nunavut "," nu "
}

def looks_canadian(loc: str | None) -> bool:
    if not loc:
        return False
    t = f" {loc.lower()} "
    if " canada " in t:
        return True
    return any(h in t for h in CANADA_HINTS)

def any_marker(text: str, markers: List[str]) -> bool:
    t = (text or "").lower()
    return any(m.lower() in t for m in markers)

def normalize_status(s: str | None) -> str:
    if not s:
        return "open"
    s = s.strip().lower()
    return "closed" if s in {"closed","filled","no longer available","not accepting applications"} else "open"

def infer_level(title: str, tags: List[str]) -> str:
    blob = f"{title} {' '.join(tags)}".lower()
    grad_kw = ["eit","graduate","masters","master’s","phd","new grad program"]
    ug_kw = ["intern","co-op","co op","coop","undergrad","bachelor","summer","student"]
    if any(k in blob for k in grad_kw):
        return "Graduate"
    if any(k in blob for k in ug_kw):
        return "Undergraduate"
    return "Undergraduate"

def map_tags(title: str, categories: Dict[str, List[str]], incoming: List[str] | None) -> List[str]:
    out = set()
    text = (title or "").lower()
    # Map by keywords
    for bucket, kws in categories.items():
        if any(k.lower() in text for k in kws):
            out.add(bucket)
    # Normalize incoming tags like "Law", "Software", "Data-ml-ai"
    for t in (incoming or []):
        tl = t.lower().replace(" ", "-")
        # exact bucket name
        if tl in categories:
            out.add(tl)
        # common spellings
        tl2 = tl.replace("-", " ")
        for bucket in categories:
            if tl == bucket or tl2 == bucket or tl2 == bucket.replace("-", " "):
                out.add(bucket)
    return sorted(out)

# ---------------- Transform ----------------

def to_posting(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "company": rec.get("company") or "Unknown",
        "role": rec.get("role") or rec.get("title") or "Intern / Co‑op",
        "location": rec.get("location"),
        "country": rec.get("location"),
        "deadline": rec.get("deadline"),
        "status": normalize_status(rec.get("status")),
        "tags": rec.get("tags") or [],
        "url": rec.get("url") or rec.get("apply_url") or rec.get("link"),
        "level": rec.get("level")
    }

def flatten_jobs_json(seed_path: str, filters_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not seed_path or not os.path.exists(seed_path):
        return []
    with open(seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Your file is: { "items": { "<url>": {record}, ... } }
    if not isinstance(data, dict) or "items" not in data or not isinstance(data["items"], dict):
        # If it's already a list, return as-is
        if isinstance(data, list):
            items = data
        else:
            return []
    else:
        items = list(data["items"].values())

    categories = get_categories(filters_cfg)
    intern_markers = get_intern_markers(filters_cfg)

    out: List[Dict[str, Any]] = []
    for it in items:
        title = it.get("title") or it.get("role") or ""
        loc = it.get("location")
        # 1) Internship filter
        if not any_marker(title, intern_markers):
            continue
        # 2) Canada-only
        if not looks_canadian(loc):
            continue
        # 3) Tag mapping + level
        tags = map_tags(title, categories, incoming=it.get("tags"))
        post = to_posting({**it, "tags": tags})
        post["level"] = post.get("level") or infer_level(post["role"], post["tags"])
        out.append(post)

    # Dedup by (company, role, url)
    dedup: Dict[tuple, Dict[str, Any]] = {}
    for r in out:
        key = (str(r.get("company","")).lower(), str(r.get("role","")).lower(), str(r.get("url","")).lower())
        dedup[key] = r
    return list(dedup.values())

# ---------------- Main ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filters", default="filters.yaml")
    ap.add_argument("--seed", default="jobs.json", help="Path to your existing jobs.json (with an 'items' dict).")
    ap.add_argument("--output", default="data/postings.json")
    ap.add_argument("--skip-live", action="store_true", help="(Placeholder) ignore live scraping; only flatten seed.")
    args = ap.parse_args()

    filters_cfg = load_yaml(args.filters)

    postings = flatten_jobs_json(args.seed, filters_cfg)


    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(postings, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(postings)} postings to {args.output}")

if __name__ == "__main__":
    sys.exit(main())
