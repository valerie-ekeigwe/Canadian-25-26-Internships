# scripts/render_readme.py
from __future__ import annotations
import json, yaml, os, sys
from datetime import datetime
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader

# ---- inputs ----
RAW_POSTINGS = os.environ.get("POSTINGS_JSON", "data/postings.json")   # [{...}]
FILTERS_YAML = os.environ.get("FILTERS_YAML", "filters.yaml")          # your filters file
TEMPLATE_DIR = os.environ.get("TEMPLATE_DIR", "templates")
TEMPLATE_NAME = os.environ.get("TEMPLATE_NAME", "readme.j2")
OUTPUT = os.environ.get("OUTPUT", "README.md")

# ---- helpers ----
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def infer_category_and_discipline(tags: list[str], tag_buckets: dict) -> tuple[str, str]:
    """
    Category = one of: Engineering, Law, Consulting, Business (you can add more)
    Discipline = for Engineering: Electrical, Chemical, Mechanical, etc.
    For Law/Consulting/Business we keep Discipline = "General" unless you want sub‑splits later.
    """
    tags_lower = {t.lower() for t in (tags or [])}

    # buckets
    eng_disciplines = {
        "electrical": "Electrical",
        "mechanical": "Mechanical",
        "civil": "Civil",
        "chemical": "Chemical",
        "mechatronics": "Mechatronics / Robotics",
        "industrial": "Industrial / Manufacturing",
        "aerospace": "Aerospace",
        "mining": "Mining / Metallurgy",
        "hardware-embedded": "Hardware / Embedded",
        "data-ml-ai": "Data / ML / AI",
        "software": "Software",
    }
    law_keys = set(tag_buckets.get("law", []))
    consulting_keys = set(tag_buckets.get("consulting", []))

    # detect Engineering discipline first
    for key, disp in eng_disciplines.items():
        if any(t in tags_lower for t in tag_buckets.get(key, [])):
            return ("Engineering", disp)

    # law
    if any(t in tags_lower for t in law_keys):
        return ("Law", "General")

    # consulting
    if any(t in tags_lower for t in consulting_keys):
        return ("Consulting", "General")

    # business heuristic: if not engineering/law/consulting and tag hints
    business_hints = {"finance","accounting","product","operations","marketing","strategy","business"}
    if tags_lower & business_hints:
        return ("Business", "General")

    # fallback
    return ("Other", "General")

def infer_level(meta: dict) -> str:
    """
    Return "Undergraduate" or "Graduate".
    Uses explicit `level` if present, else keyword inference on role/title/tags.
    """
    level = (meta.get("level") or "").lower()
    if "under" in level or level == "ug" or level == "undergraduate":
        return "Undergraduate"
    if "grad" in level or "eit" in level or "phd" in level or "master" in level:
        return "Graduate"

    text = " ".join(filter(None, [
        meta.get("role",""), meta.get("title",""), " ".join(meta.get("tags", []))
    ])).lower()

    ug_kw = ["intern","co-op","co op","coop","undergrad","bachelor"]
    grad_kw = ["eit","graduate","masters","master’s","phd","new grad program"]

    if any(k in text for k in grad_kw):
        return "Graduate"
    if any(k in text for k in ug_kw):
        return "Undergraduate"
    # default
    return "Undergraduate"

def normalize_status(s: str | None) -> str:
    s = (s or "open").strip().lower()
    return "closed" if s in {"closed","no longer available","filled"} else "open"

def sort_key(p):
    # prioritize deadline if ISO‑like, else push to bottom
    d = p.get("deadline") or ""
    return (d if d and len(d) >= 4 else "9999-99-99", p.get("company","").lower())

def build_groups(rows: list[dict], filters: dict) -> dict:
    tag_buckets = filters.get("categories", {})
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # cat -> disc -> level -> list

    for r in rows:
        # Skip anything not Canada (your scraper should already filter, this is a safety net)
        country = (r.get("country") or r.get("location") or "").lower()
        if "canada" not in country and not any(k in country for k in ["on","qc","bc","ab","sk","mb","nb","ns","nl","pe","yt","nt","nu","toronto","montreal","vancouver","calgary","edmonton","ottawa","waterloo"]):
            continue

        tags = r.get("tags") or []
        category, discipline = infer_category_and_discipline(tags, tag_buckets)
        level = infer_level(r)
        status = normalize_status(r.get("status"))

        post = {
            "company": r.get("company") or r.get("org") or "Unknown",
            "role": r.get("role") or r.get("title") or "Intern / Co‑op",
            "location": r.get("city_province") or r.get("location"),
            "deadline": r.get("deadline"),
            "status": status,
            "tags": tags,
            "url": r.get("url") or r.get("apply_url") or r.get("link"),
        }
        groups[category][discipline][level].append(post)

    # sort each bucket
    for cat in groups.values():
        for disc in cat.values():
            for lvl, posts in disc.items():
                posts.sort(key=sort_key)

    return groups

def main():
    rows = load_json(RAW_POSTINGS)   # expects a list of postings from your scraper
    filters = load_yaml(FILTERS_YAML)
    groups = build_groups(rows, filters)

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=False, trim_blocks=True, lstrip_blocks=True)
    tpl = env.get_template(TEMPLATE_NAME)
    md = tpl.render(
        groups=groups,
        generated_at=datetime.now().strftime("%Y-%m-%d")
    )
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote {OUTPUT} with {sum(len(levels) for disc in groups.values() for levels in disc.values())} sections.")

if __name__ == "__main__":
    sys.exit(main())
