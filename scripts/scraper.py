# scripts/scraper.py
from __future__ import annotations
import os, sys, json, re, argparse
from typing import Any, Dict, List
import yaml

# Optional: only needed if you want to scrape live boards in addition to flattening jobs.json
try:
    import requests
except ImportError:
    requests = None

INTERN_MARKERS_DEFAULT = [
    "intern","co-op","co op","coop","student","summer","placement","industrial placement"
]

CANADA_HINTS = [
    "canada","toronto","ontario","on","ottawa","waterloo","london",
    "montreal","québec","quebec","qc","laval","sherbrooke","trois-rivières",
    "vancouver","british columbia","bc","burnaby","victoria","surrey",
    "calgary","edmonton","alberta","ab",
    "saskatchewan","sk","regina","saskatoon",
    "manitoba","mb","winnipeg",
    "new brunswick","nb","saint john","moncton","fredericton",
    "nova scotia","ns","halifax",
    "newfoundland","nl","st. john’s","st johns",
    "prince edward island","pei","charlottetown",
    "yukon","yt","whitehorse","northwest territories","nt","nunavut","nu"
]

# ----------------- helpers -----------------
def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def looks_canadian(loc: str | None) -> bool:
    if not loc:
        return False
    t = loc.lower()
    if "canada" in t:
        return True
    return any(f" {h} " in f" {t} " for h in CANADA_HINTS)

def any_marker(text: str, markers: List[str]) -> bool:
    t = (text or "").lower()
    return any(m.lower() in t for m in markers)

def normalize_status(s: str | None) -> str:
    if not s:
        return "open"
    s = s.strip().lower()
    return "closed" if s in {"closed","filled","no longer available"} else "open"

def infer_level(title: str, tags: List[str]) -> str:
    blob = f"{title} {' '.join(tags)}".lower()
    grad_kw = ["eit","graduate","masters","master’s","phd","new grad program"]
    ug_kw = ["intern","co-op","co op","coop","undergrad","bachelor","summer"]
    if any(k in blob for k in grad_kw):
        return "Graduate"
    if any(k in blob for k in ug_kw):
        return "Undergraduate"
    return "Undergraduate"

def map_tags(title: str, desc: str, filters_cfg: Dict[str, Any], incoming: List[str] | None = None) -> List[str]:
    tags = set()
    text = f"{title} {desc}".lower()
    cats = ((filters_cfg.get("filters") or {}).get("categories") or {})
    for bucket, kws in cats.items():
        if any(k.lower() in text for k in kws):
            tags.add(bucket)
    for t in (incoming or []):
        t_low = t.lower()
        # If incoming tag matches a known bucket name, keep it as that bucket
        if t_low in cats.keys():
            tags.add(t_low)
        # Friendly mapping for common inputs like "Law", "Software"
        for bucket in cats.keys():
            if t_low == bucket.replace("-", " "):
                tags.add(bucket)
    return sorted(tags)

def to_posting(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "company": obj.get("company") or "Unknown",
        "role": obj.get("role") or obj.get("title") or "Intern / Co‑op",
        "location": obj.get("location"),
        "country": obj.get("location"),
        "deadline": obj.get("deadline"),
        "status": normalize_status(obj.get("status")),
        "tags": obj.get("tags") or [],
        "url": obj.get("url") or obj.get("apply_url") or obj.get("link"),
        "level": obj.get("level")
    }

# --------------- flatten existing jobs.json ---------------
def flatten_seed(seed_path: str, filters_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not seed_path or not os.path.exists(seed_path):
        return []
    with open(seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []
    # Your file uses {"items": { "<url>": {...}, ...}}
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], dict):
        for _k, v in data["items"].items():
            items.append(v)
    elif isinstance(data, list):
        items = data
    else:
        # Unknown shape; bail out gracefully
        return []

    intern_markers = ((filters_cfg.get("filters") or {}).get("intern_markers") or INTERN_MARKERS_DEFAULT)

    out: List[Dict[str, Any]] = []
    for it in items:
        title = it.get("title") or it.get("role") or ""
        # keep only internships/co-ops
        if not any_marker(title, intern_markers):
            continue
        # keep only Canadian
        if not looks_canadian(it.get("location") or ""):
            continue
        # map tags to buckets
        tags = map_tags(title, "", filters_cfg, incoming=it.get("tags"))
        post = to_posting({**it, "tags": tags})
        # fill inferred fields
        post["level"] = post.get("level") or infer_level(post["role"], post["tags"])
        out.append(post)
    return out

# --------------- optional live scraping (GH/Lever/Ashby) ---------------
def gh_jobs(board: str) -> List[Dict[str, Any]]:
    if not requests:
        return []
    url = f"https://api.greenhouse.io/v1/boards/{board}/jobs"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json().get("jobs", [])
    except Exception:
        return []

def lv_jobs(company: str) -> List[Dict[str, Any]]:
    if not requests:
        return []
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def ab_jobs(board: str) -> List[Dict[str, Any]]:
    if not requests:
        return []
    url = f"https://jobs.ashbyhq.com/api/non-user-boards/{board}"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json().get("jobs", [])
    except Exception:
        return []

def scrape_from_filters(filters_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    intern_markers = ((filters_cfg.get("filters") or {}).get("intern_markers") or INTERN_MARKERS_DEFAULT)
    results: List[Dict[str, Any]] = []

    # --- Greenhouse ---
    for gh in (filters_cfg.get("greenhouse") or []):
        board_url = gh.get("board","")
        board = board_url.rstrip("/").split("/")[-1] if board_url else ""
        if not board:
            continue
        for j in gh_jobs(board):
            title = j.get("title") or ""
            loc = (j.get("location") or {}).get("name") or ""
            if not any_marker(title, intern_markers):
                continue
            if not looks_canadian(loc):
                continue
            post = {
                "company": gh.get("name") or "Unknown",
                "role": title,
                "location": loc,
                "country": loc,
                "deadline": None,
                "status": "open",
                "tags": map_tags(title, "", filters_cfg),
                "url": j.get("absolute_url"),
                "level": infer_level(title, [])
            }
            results.append(post)

    # --- Lever ---
    for lv in (filters_cfg.get("lever") or []):
        company = (lv.get("board") or lv.get("name","")).rstrip("/").split("/")[-1]
        if not company:
            continue
        for j in lv_jobs(company):
            title = j.get("text") or ""
            loc = j.get("categories", {}).get("location") or ""
            if not any_marker(title, intern_markers):
                continue
            if not looks_canadian(loc):
                continue
            post = {
                "company": lv.get("name") or (j.get("categories", {}).get("department") or "Unknown"),
                "role": title,
                "location": loc,
                "country": loc,
                "deadline": None,
                "status": "open",
                "tags": map_tags(title, j.get("categories", {}).get("team") or "", filters_cfg),
                "url": j.get("hostedUrl") or j.get("applyUrl"),
                "level": infer_level(title, [])
            }
            results.append(post)

    # --- Ashby ---
    for ab in (filters_cfg.get("ashby") or []):
        board = (ab.get("board") or "").rstrip("/").split("/")[-1]
        if not board:
            continue
        for j in ab_jobs(board):
            title = j.get("title") or ""
            loc = j.get("locationName") or ""
            if not any_marker(title, intern_markers):
                continue
            if not looks_canadian(loc):
                continue
            post = {
                "company": ab.get("name") or (j.get("organizationName") or "Unknown"),
                "role": title,
                "location": loc,
                "country": loc,
                "deadline": None,
                "status": "open",
                "tags": map_tags(title, j.get("teamName") or "", filters_cfg),
                "url": j.get("jobUrl"),
                "level": infer_level(title, [])
            }
            results.append(post)

    return results

# --------------- main ---------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filters", default="filters.yaml")
    ap.add_argument("--output", default="data/postings.json")
    ap.add_argument("--seed", default="jobs.json", help="Optional existing jobs file to flatten (dictionary with 'items').")
    ap.add_argument("--skip-live", action="store_true", help="Only flatten seed; skip live scraping.")
    args = ap.parse_args()

    filters_cfg = load_yaml(args.filters)

    final: List[Dict[str, Any]] = []

   
    seed_posts = flatten_seed(args.seed, filters_cfg)
    final.extend(seed_posts)

   
    if not args.skip_live:
        final.extend(scrape_from_filters(filters_cfg))

   
    dedup: Dict[tuple, Dict[str, Any]] = {}
    for r in final:
        key = (str(r.get("company","")).lower(), str(r.get("role","")).lower(), str(r.get("url","")).lower())
        dedup[key] = r
    final_list = list(dedup.values())

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(final_list, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(final_list)} postings to {args.output}")

if __name__ == "__main__":
    main()
