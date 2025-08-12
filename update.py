import yaml
import requests
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

# ---------- CONFIG ----------
ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "sources.yaml"
TEMPLATE_FILE = ROOT / "templates"
OUTPUT_FILE = ROOT / "README.md"

# Load source configuration
with open(DATA_FILE, "r") as f:
    config = yaml.safe_load(f)

def fetch_jobs():
    jobs = []
    events = []

    # Placeholder — In real use, you'd scrape or call APIs here
    # We'll just pull from "manual" for now so you have working output
    for m in config.get("manual", []):
        jobs.append({
            "company": m["company"],
            "title": m.get("title_hint", ""),
            "location": m.get("location", ""),
            "source": "manual",
            "url": m.get("url", "")
        })

    # If we have events section
    for e in config.get("events", []):
        events.append({
            "name": e["name"],
            "field": e.get("field", ""),
            "date": e.get("date", ""),
            "location": e.get("location", ""),
            "url": e.get("url", "")
        })

    return jobs, events

def render_readme(jobs, events):
    env = Environment(loader=FileSystemLoader(TEMPLATE_FILE))
    template = env.get_template("README.md.j2")

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    fresh_jobs = jobs[:5]  # Pretend top 5 are "fresh" for demo

    readme_content = template.render(
        generated_at=now_str,
        fresh=fresh_jobs,
        all=jobs,
        events=events
    )

    OUTPUT_FILE.write_text(readme_content, encoding="utf-8")
    print(f"README.md updated at {now_str}")

if __name__ == "__main__":
    jobs, events = fetch_jobs()
    render_readme(jobs, events)
