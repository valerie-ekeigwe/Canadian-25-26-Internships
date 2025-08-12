import sys, json, datetime as dt, re
from pathlib import Path
from typing import List, Dict, Any
import requests, yaml
from jinja2 import Environment, FileSystemLoader
from bs4 import BeautifulSoup

# ── Paths
ROOT = Path(__file__).parent
DATA = ROOT / "data" / "sources.yaml"
TPL_DIR = ROOT / "templates"
OUT_MD = ROOT / "README.md"
REGISTRY = ROOT / "jobs.json"

# ── HTTP
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Canadian-Internships-Auto/1.3"})

# ── Helpers
def now_str(): return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def load_yaml(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_json(p: Path, default):
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return default
    return default

def save_json(p: Path, obj):
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def is_intern(title: str, markers: List[str]) -> bool:
    t = (title or "").lower()
    return any(m in t for m in markers)

def tags_for(title: str, cat_map: Dict[str, List[str]]) -> List[str]:
    t = (title or "").lower()
    hits = []
    for key, kws in cat_map.items():
        if any(k in t for k in kws):
            hits.append(key)
    return [k.capitalize() for k in hits] or ["General"]

def norm_url(base: str, href: str) -> str:
    if not href: return ""
    if href.startswith("http"): return href
    return base.rstrip("/") + "/" + href.lstrip("/")

def normalize(company, title, url, location, source, markers, cat_map) -> Dict[str, Any] | None:
    if not title or not url: return None
    if not is_intern(title, markers): return None
    return {
        "company": (company or "").strip(),
        "title": title.strip(),
        "url": url.strip(),
        "location": (location or "").strip() or None,
        "source": source,
        "tags": tags_for(title, cat_map),
        # Optional fields if you later parse them:
        "posted": None,
        "deadline": None,
        "notes": None,
    }

# ── Fetchers
def fetch_lever(name, board_url, markers, cat_map):
    url = board_url.rstrip("/") + ".json"
    r = SESSION.get(url, timeout=30); r.raise_for_status()
    out = []
    for p in r.json().get("positions", []):
        row = normalize(
            company=name,
            title=p.get("text",""),
            url=p.get("hostedUrl") or p.get("applyUrl") or "",
            location=(p.get("categories") or {}).get("location"),
            source="Lever",
            markers=markers, cat_map=cat_map
        )
        if row: out.append(row)
    return out

def fetch_greenhouse(name, api_base, markers, cat_map):
    r = SESSION.get(api_base.rstrip("/") + "/jobs", timeout=30); r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        row = normalize(
            company=name,
            title=j.get("title",""),
            url=j.get("absolute_url") or "",
            location=(j.get("location") or {}).get("name"),
            source="Greenhouse",
            markers=markers, cat_map=cat_map
        )
        if row: out.append(row)
    return out

def fetch_ashby(name, api_url, markers, cat_map):
    r = SESSION.get(api_url, timeout=30); r.raise_for_status()
    data = r.json(); jobs = data.get("jobs") or data
    out = []
    for j in jobs:
        row = normalize(
            company=name,
            title=j.get("title",""),
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            location=j.get("locationName") or j.get("location"),
            source="Ashby",
            markers=markers, cat_map=cat_map
        )
        if row: out.append(row)
    return out

def fetch_html(name, board_url, markers, cat_map, label):
    r = SESSION.get(board_url, timeout=30); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.find_all("a"):
        txt = (a.get_text() or "").strip()
        href = a.get("href") or ""
        if not txt or not href: continue
        if is_intern(txt, markers):
            row = normalize(name, txt, norm_url(board_url, href), None, label, markers, cat_map)
            if row: out.append(row)
    return out

def fetch_manual(manual, markers, cat_map):
    out = []
    for e in manual or []:
        row = normalize(
            e.get("company"), e.get("title_hint","Internship"), e.get("url"),
            e.get("location"), "Manual", markers, cat_map
        )
        if row: out.append(row)
    return out

# ── Collect
def collect_all(cfg) -> List[Dict[str,Any]]:
    filters = cfg["filters"]
    markers = filters["intern_markers"]
    cat_map = filters["categories"]
    rows: List[Dict[str,Any]] = []

    for s in cfg.get("lever", []):
        try: rows += fetch_lever(s["name"], s["board"], markers, cat_map)
        except Exception as e: print("[warn] Lever", s["name"], e)

    for s in cfg.get("greenhouse", []):
        try: rows += fetch_greenhouse(s["name"], s["board"], markers, cat_map)
        except Exception as e: print("[warn] Greenhouse", s["name"], e)

    for s in cfg.get("ashby", []):
        try: rows += fetch_ashby(s["name"], s["board"], markers, cat_map)
        except Exception as e: print("[warn] Ashby", s["name"], e)

    for s in cfg.get("workday", []):
        try: rows += fetch_html(s["name"], s["board"], markers, cat_map, "Workday")
        except Exception as e: print("[warn] Workday", s["name"], e)

    for s in cfg.get("taleo", []):
        try: rows += fetch_html(s["name"], s["board"], markers, cat_map, "Taleo")
        except Exception as e: print("[warn] Taleo", s["name"], e)

    for s in cfg.get("smartrecruiters", []):
        try: rows += fetch_html(s["name"], s["board"], markers, cat_map, "SmartRecruiters")
        except Exception as e: print("[warn] SmartRecruiters", s["name"], e)

    rows += fetch_manual(cfg.get("manual"), markers, cat_map)

    # Dedupe and sort (prefer Canadian locations)
    seen = set(); dedup = []
    for r in rows:
        key = (r["company"].lower(), r["title"].lower(), r["url"])
        if key in seen: continue
        seen.add(key); dedup.append(r)

    def is_can(loc):
        if not loc: return 0
        l = loc.lower()
        hits = ["canada","toronto","ottawa","montreal","vancouver","calgary","edmonton","waterloo","mississauga",
                "ontario","quebec","british columbia","alberta","manitoba","saskatchewan","nova scotia","new brunswick","pei","yukon","nunavut"]
        return 1 if any(h in l for h in hits) else 0

    dedup.sort(key=lambda x: (-is_can(x.get("location")), x["company"], x["title"]))
    return dedup

# ── Registry merge (auto Open/Closed)
def merge_registry(new_rows: List[Dict[str,Any]], reg: Dict[str,Any]):
    now = now_str()
    items = reg.setdefault("items", {})
    idx = {r["url"]: r for r in new_rows}

    # Update existing
    for url, item in list(items.items()):
        if url in idx:
            item["status"] = "Open"
            item["updated_at"] = now
            for k in ["company","title","location","source","tags","posted","deadline","notes"]:
                item[k] = idx[url].get(k, item.get(k))
        else:
            item["status"] = "Closed"
            item["updated_at"] = now

    # Add new
    for r in new_rows:
        if r["url"] not in items:
            items[r["url"]] = {**r, "status": "Open", "created_at": now, "updated_at": now}
    return reg

# ── Markdown table builders
def md_table(rows: List[Dict[str,Any]]) -> str:
    if not rows:
        return "| _No entries yet._ |\n"
    header = "| Company | Role | City/Province | Posted | Deadline | Notes | Status | Link |\n|---|---|---|---|---|---|---|---|\n"
    lines = []
    for r in rows:
        lines.append(f"| {r['company']} | {r['title']} | {r.get('location') or '—'} | "
                     f"{r.get('posted') or 'Rolling/unspecified'} | {r.get('deadline') or 'Rolling/unspecified'} | "
                     f"{r.get('notes') or '—'} | {'Open' if r.get('status')!='Closed' else 'Closed'} | [Apply]({r['url']}) |")
    return header + "\n".join(lines) + "\n"

def bucketize(items: List[Dict[str,Any]]):
    b = {
        "software": [],
        "mechanical": [],
        "mechatronics": [],
        "electrical_hw": [],
        "law_consulting": [],
    }
    for i in items:
        tset = set([t.lower() for t in (i.get("tags") or [])])
        if any(x in tset for x in ["software","data-ml-ai"]):
            b["software"].append(i)
        if "mechanical" in tset:
            b["mechanical"].append(i)
        if any(x in tset for x in ["mechatronics","hardware-embedded","robotics"]):
            b["mechatronics"].append(i)
        if any(x in tset for x in ["electrical","hardware-embedded","hardware","computer"]):
            b["electrical_hw"].append(i)
        if any(x in tset for x in ["law","consulting"]):
            b["law_consulting"].append(i)
    return b

# ── Render
def render_readme(reg: Dict[str,Any], opps: Dict[str,Any]):
    env = Environment(loader=FileSystemLoader(str(TPL_DIR)))
    tpl = env.get_template("README.md.j2")
    items = list(reg.get("items", {}).values())
    items.sort(key=lambda x: (x["company"], x["title"]))

    # Fresh = updated or created in last 7 days
    def is_recent(ts: str | None):
        if not ts: return False
        try:
            t = dt.datetime.strptime(ts.replace(" UTC",""), "%Y-%m-%d %H:%M")
            return (dt.datetime.utcnow() - t).days <= 7
        except Exception:
            return False
    fresh = [i for i in items if is_recent(i.get("updated_at") or i.get("created_at"))]

    # Build buckets and tables
    buckets = bucketize(items)
    tables = {k: md_table(v) for k, v in buckets.items()}

    # Build opportunities lists (simple passthrough)
    opps = opps or {}
    return tpl.render(
        generated_at=now_str(),
        tables=tables,
        fresh=fresh,
        opps=opps
    )

def main():
    cfg = load_yaml(DATA)
    reg = load_json(REGISTRY, {"items": {}})

    new_rows = collect_all(cfg)
    reg = merge_registry(new_rows, reg)

    md = render_readme(reg, cfg.get("opportunities"))
    old = OUT_MD.read_text(encoding="utf-8") if OUT_MD.exists() else ""
    if md.strip() != old.strip():
        OUT_MD.write_text(md, encoding="utf-8")
        print("README updated.")
    else:
        print("No README changes.")
    save_json(REGISTRY, reg)
    return 0

if __name__ == "__main__":
    sys.exit(main())
