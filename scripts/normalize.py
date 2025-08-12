# scripts/normalize.py
import json, re, sys
from pathlib import Path

INPUT = Path("data/postings.json")
OUTPUT = Path("data/postings.json")

if not INPUT.exists():
    sys.exit("data/postings.json is missing")

raw = json.loads(INPUT.read_text(encoding="utf-8"))
arr = raw if isinstance(raw, list) else list(raw.get("items", {}).values())

# Canada matcher
CAN_HINTS = [
  " canada "," toronto "," ontario "," on "," ottawa "," waterloo "," montreal ",
  " québec "," quebec "," qc "," vancouver "," british columbia "," bc ",
  " calgary "," edmonton "," alberta "," ab "," manitoba "," mb "," winnipeg ",
  " saskatchewan "," sk "," regina "," saskatoon ",
  " nova scotia "," ns "," halifax "," new brunswick "," nb ",
  " pei "," prince edward island "," newfoundland "," nl ",
  " st. john’s "," st johns "," yukon "," whitehorse "," northwest territories "," nt ",
  " nunavut "," nu "
]
def is_canadian(loc: str|None) -> bool:
    if not loc: return False
    t = f" {loc.lower()} "
    return (" canada " in t) or any(h in t for h in CAN_HINTS)

# STRICT intern/co-op regex (avoids "International")
INTERN_RE = re.compile(r"\b(intern(ship)?|co[- ]?op|coop|student|summer|placement)\b", re.I)
def is_internish(role: str|None) -> bool:
    return bool(INTERN_RE.search(role or ""))

def norm_status(s):
    if not s: return "Open"
    s = s.strip().lower()
    return "Closed" if s in {"closed","filled","no longer available","not accepting applications"} else "Open"

def infer_level(role, tags):
    blob = f"{(role or '').lower()} {' '.join(tags or [])}"
    if any(k in blob for k in ["eit","graduate","masters","master’s","phd","new grad program","articling"]):
        return "Graduate"
    if any(k in blob for k in ["intern","co-op","co op","coop","undergrad","bachelor","summer","student","law student"]):
        return "Undergraduate"
    return "Undergraduate"

# Tag buckets (matches your filters.yaml buckets)
BUCKETS = {
  "software": ["software","swe","developer","full stack","frontend","backend","mobile","android","ios","web"],
  "mechatronics": ["mechatronics","robotics","autonomy","controls","automation"],
  "electrical": ["electrical","electronics","power systems","pcb","circuit","firmware","substation","distribution"],
  "mechanical": ["mechanical","thermodynamics","hvac","cad","solidworks","catia","ansys","fea","manufacturing engineer"],
  "civil": ["civil","structural","municipal","transportation","geotech","construction"],
  "chemical": ["chemical","process","petroleum","refining","materials"],
  "industrial": ["industrial","manufacturing","lean","six sigma","operations","quality","supply chain","process engineer"],
  "aerospace": ["aerospace","avionics","space","propulsion","aerodynamics","satellite","uav"],
  "mining": ["mining","metallurgy","mine","geology","geoscience"],
  "data-ml-ai": ["data","ml","machine learning","ai","analytics","business intelligence","science"],
  "hardware-embedded": ["embedded","fpga","asic","verilog","vhdl","rtl","hardware","micros","risc","arm"],
  "law": ["legal","law","paralegal","policy","compliance","regulatory","litigation","clerk","law student"],
  "consulting": ["consultant","consulting","strategy","advisory","analytics","transformation","risk","deal","operations"],
  "business": ["business","finance","marketing","accounting","economics","management","sales","hr","operations"],
}

# Company hints to auto-tag generic titles
COMPANY_HINTS = {
  # Auto OEMs
  "ford": ["mechanical","electrical","industrial"],
  "toyota": ["mechanical","electrical","industrial"],
  "honda": ["mechanical","electrical","industrial"],
  "stellantis": ["mechanical","electrical","industrial"],
  "gm": ["mechanical","electrical","industrial"],
  "general motors": ["mechanical","electrical","industrial"],
  # Law
  "blg": ["law"], "bennett jones": ["law"], "blake, cassels": ["law"], "cassels": ["law"],
  "stikeman": ["law"], "torys": ["law"], "goodmans": ["law"], "gowling": ["law"],
  "mccarthy": ["law"], "norton rose": ["law"], "supreme court of canada": ["law"],
  # Consulting (if added later)
  "deloitte": ["consulting"], "kpmg": ["consulting"], "pwc": ["consulting"], "ey": ["consulting"], "mckinsey": ["consulting"],
}

def map_tags(company, role, incoming):
    out = set()
    text = (role or "").lower()
    for b, kws in BUCKETS.items():
        if any(k in text for k in kws):
            out.add(b)
    for t in incoming or []:
        tl = (t or "").lower().replace(" ", "-")
        if tl in BUCKETS: out.add(tl)
        for b in BUCKETS:
            if tl == b or tl == b.replace("-", " "): out.add(b)
    cl = (company or "").lower()
    for key, buckets in COMPANY_HINTS.items():
        if key in cl:
            out.update(buckets)
    return sorted(out) if out else ["general"]

clean = []
for r in arr:
    role = r.get("role") or r.get("title") or ""
    loc  = r.get("location")
    if not is_internish(role):
        continue
    if not is_canadian(loc):
        continue
    tags = map_tags(r.get("company"), role, r.get("tags"))
    clean.append({
        "company": r.get("company") or "Unknown",
        "role": role,
        "location": loc,
        "country": "Canada",
        "deadline": r.get("deadline") or "Rolling/unspecified",
        "status": norm_status(r.get("status")),
        "tags": tags,
        "url": r.get("url") or r.get("apply_url") or r.get("link"),
        "level": infer_level(role, tags),
    })

# de-dupe
seen = {}
for c in clean:
    key = (c["company"].lower(), c["role"].lower(), (c["url"] or "").lower())
    seen[key] = c
final = list(seen.values())

OUTPUT.write_text(json.dumps(final, indent=2, ensure_ascii=False))
print("normalized rows:", len(final))
if not final:
    sys.exit("No Canadian intern/co-op rows found after normalization.")
