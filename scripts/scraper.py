# scripts/scraper.py
from __future__ import annotations
import os, sys, json, re, time
from typing import Dict, List, Any
from urllib.parse import urljoin

import yaml
import requests

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Canadian-Internships-Scraper/1.0"})

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

def load_filters(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def any_in(text: str, needles: List[str]) -> bool:
    t = text.lower()
    return any(n.lower() in t for n in needles)

def looks_canadian(loc: str) -> bool:
    if not loc:
        return False
    t = loc.lower()
    return "canada" in t or any(f" {h} " in f" {t} " for h in CANADA_HINTS)

def tag_posting(title: str, description: str, filters: Dict[str, Any]) -> List[str]:
    tags = []
    t = f"{title} {description}".lower()
    for bucket_key, keywords in (filters.get("filters", {}).get("categories", {}) or {}).items():
        if any(k.lower() in t for k in keywords):
            tags.append(bucket_key)
    return sorted(set(tags))

def infer_level(title: str, desc: str, explicit: str | None = None) -> str:
    if explicit:
        e = explicit.lower()
        if "grad" in e or "eit" in e or "master" in e or "phd" in e:
            return "Graduate"
        if "ug" in e or "under" in e or "bachelor" in e:
            return "Undergraduate"
    blob = f"{title} {desc}".lower()
    grad_kw = ["eit","graduate","masters","master’s","phd","new grad program"]
    ug_kw = ["intern","co-op","co op","coop","undergrad","bachelor"]
    if any(k in blob for k in grad_kw):
        return "Graduate"
    if any(k in blob for k in ug_kw):
        return "Undergraduate"
    return "Undergraduate"

def normalize_deadline(raw: Any) -> str | None:
    # Many boards don’t provide deadlines; keep None or "Rolling/unspecified" in renderer
    if not raw:
        return None
    s = str(raw).strip()
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else s

def basic_filter_pass(title: str, filters_cfg: Dict[str, Any]) -> bool:
    intern_markers = (filters_cfg.get("filters", {}).get("intern_markers") or [])
    return any_in(title, intern_markers)

def greenhouse_fetch(board: str) -> List[Dict[str, Any]]:
    # API ref: https://api.greenhouse.io/v1/boards/{board}/jobs
    url = f"https://api.greenhouse.io/v1/boards/{board}/jobs"
    try:
        r = SESSION.get(url, timeout=25)
        r.raise_for_status()
        data = r.json()
        return data.get("jobs", [])
    except Exception as e:
        print(f"[greenhouse:{board}] error: {e}", file=sys.stderr)
        return []

def lever_fetch(company: str) -> List[Dict[str, Any]]:
    # API: https://api.lever.co/v0/postings/{company}?mode=json
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    try:
        r = SESSION.get(url, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[lever:{company}] error: {e}", file=sys.stderr)
        return []

def ashby_fetch(board: str) -> List[Dict[str, Any]]:
    # API: https://jobs.ashbyhq.com/api/non-user-boards/{board}
    url = f"https://jobs.ashbyhq.com/api/non-user-boards/{board}"
    try:
        r = SESSION.get(url, timeout=25)
        r.raise_for_status()
        return r.json().get("jobs", [])
    except Exception as e:
        print(f"[ashby:{board}] error: {e}", file=sys.stderr)
        return []

def to_common_from_greenhouse(job: Dict[str, Any]) -> Dict[str, Any]:
    title = job.get("title") or ""
    loc = (job.get("location") or {}).get("name") or ""
    url = job.get("absolute_url") or ""
    dep = job.get("departments") or []
    dept_text = " ".join([d.get("name","") for d in dep])
    return {
        "company": (job.get("company") or job.get("offices") or [{}])[0].get("name","") or "",  # often empty
        "role": title,
        "location": loc,
        "country": loc,
        "deadline": None,
        "status": "open",
        "tags": [],
        "url": url,
        "extra_text": dept_text
    }

def to_common_from_lever(job: Dict[str, Any]) -> Dict[str, Any]:
    title = job.get("text") or ""
    locs = job.get("categories", {}).get("location") or ""
    url = job.get("hostedUrl") or job.get("applyUrl") or ""
    team = job.get("categories", {}).get("team") or ""
    return {
        "company": job.get("categories", {}).get("department") or job.get("company") or "",
        "role": title,
        "location": locs,
        "country": locs,
        "deadline": None,
        "status": "open",
        "tags": [],
        "url": url,
        "extra_text": team
    }

def to_common_from_ashby(job: Dict[str, Any]) -> Dict[str, Any]:
    title = job.get("title") or ""
    loc = (job.get("locationName") or job.get("employmentType") or "")
    url = job.get("jobUrl") or ""
    dept = job.get("teamName") or ""
    return {
        "company": job.get("organizationName") or "",
        "role": title,
        "location": loc,
        "country": loc,
        "deadline": None,
        "status": "open",
        "tags": [],
        "url": url,
        "extra_text": dept
    }

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--filters", default="filters.yaml")
    ap.add_argument("--output", default="data/postings.json")
    args = ap.parse_args()

    filters_cfg = load_filters(args.filters)

    results: List[Dict[str, Any]] = []

    # --- GREENHOUSE ---
    for gh in (filters_cfg.get("greenhouse") or []):
        board_url = gh.get("board","")
        # accept both api url and short form
        if "api.greenhouse.io" in board_url:
            board = board_url.rstrip("/").split("/")[-1]
        else:
            board = gh.get("name","").lower()
        if not board:
            continue
        for job in greenhouse_fetch(board):
            c = to_common_from_greenhouse(job)
            # heuristic company fallback
            if not c["company"]:
                # some boards include company in 'absolute_url' path; leave blank if unknown
                c["company"] = gh.get("name","")
            if not basic_filter_pass(c["role"], filters_cfg):
                continue
            if not looks_canadian(c["location"]):
                continue
            # tag + infer
            c["tags"] = tag_posting(c["role"], c.get("extra_text",""), filters_cfg)
            c["level"] = infer_level(c["role"], c.get("extra_text",""))
            results.append(c)

    # --- LEVER ---
    for lv in (filters_cfg.get("lever") or []):
        company = (lv.get("board") or lv.get("name","")).rstrip("/").split("/")[-1]
        if not company:
            continue
        for job in lever_fetch(company):
            c = to_common_from_lever(job)
            if not basic_filter_pass(c["role"], filters_cfg):
                continue
            if not looks_canadian(c["location"]):
                continue
            c["company"] = lv.get("name","") or c["company"]
            c["tags"] = tag_posting(c["role"], c.get("extra_text",""), filters_cfg)
            c["level"] = infer_level(c["role"], c.get("extra_text",""))
            results.append(c)

    # --- ASHBY ---
    for ab in (filters_cfg.get("ashby") or []):
        board = (ab.get("board") or "").rstrip("/").split("/")[-1]
        if not board:
            continue
        for job in ashby_fetch(board):
            c = to_common_from_ashby(job)
            if not basic_filter_pass(c["role"], filters_cfg):
                continue
            if not looks_canadian(c["location"]):
                continue
            c["company"] = ab.get("name","") or c["company"]
            c["tags"] = tag_posting(c["role"], c.get("extra_text",""), filters_cfg)
            c["level"] = infer_level(c["role"], c.get("extra_text",""))
            results.append(c)

    # TODO: SmartRecruiters, Workday, Taleo, Manual (can be added later)

    # Dedup by (company, role, url)
    dedup = {}
    for r in results:
        key = (r.get("company","").lower(), r.get("role","").lower(), r.get("url","").lower())
        dedup[key] = r
    final = list(dedup.values())

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(final)} postings to {args.output}")

if __name__ == "__main__":
    main()
