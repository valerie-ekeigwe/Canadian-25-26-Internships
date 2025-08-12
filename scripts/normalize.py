import json
from datetime import datetime

INPUT_FILE = "data/postings.json"
OUTPUT_FILE = "data/postings.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    postings = json.load(f)

# Filter out empty/invalid rows
postings = [
    p for p in postings
    if p.get("Company") and p.get("Role") and p.get("Location")
]

# Sort by Company name
postings.sort(key=lambda x: x.get("Company", "").lower())

# Add or update "LastUpdated" field
for p in postings:
    p["LastUpdated"] = datetime.utcnow().strftime("%Y-%m-%d")

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(postings, f, ensure_ascii=False, indent=2)

print(f"Normalized {len(postings)} postings and saved to {OUTPUT_FILE}")
