"""Export bot data to JSON for the static dashboard."""

import json
import logging
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

from src.stores.db import get_events

PROJECTS_DIR = Path("projects")
DASHBOARD_DIR = Path("dashboard/data")


def parse_messages_txt(path: Path) -> list[dict]:
    """Parse a messages.txt file into structured entries."""
    entries = []
    if not path.exists():
        return entries
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split(" | ", 4)
        if len(parts) < 5:
            continue
        # Strip <@...> wrapper from user ID
        user_raw = parts[1].strip()
        user_id = re.search(r"<@([A-Z0-9]+)>", user_raw)
        entries.append({
            "timestamp": parts[0].strip(),
            "user": user_id.group(1) if user_id else user_raw,
            "permalink": parts[2].strip(),
            "category": parts[3].strip(),
            "summary": parts[4].strip(),
        })
    return entries


def build_stats(events: list[dict]) -> dict:
    """Build per-project stats from SQLite events."""
    by_type: dict[str, int] = defaultdict(int)
    by_category: dict[str, int] = defaultdict(int)
    by_day: dict[str, int] = defaultdict(int)
    total_with_reaction = 0
    total_approved = 0

    for event in events:
        by_type[event["event_type"]] += 1
        by_category[event["category"]] += 1
        day = event["timestamp"][:10]
        by_day[day] += 1
        if event.get("reaction"):
            total_with_reaction += 1
            if event["reaction"] == "approved":
                total_approved += 1

    return {
        "by_type": dict(by_type),
        "by_category": dict(by_category),
        "by_day": dict(sorted(by_day.items())),
        "total_events": len(events),
        "total_with_reaction": total_with_reaction,
        "total_approved": total_approved,
        "acceptance_rate": round(total_approved / total_with_reaction * 100) if total_with_reaction else 0,
    }


def export(project_name: str):
    """Export a single project's data to dashboard/data/ as JSON."""
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    project_dir = PROJECTS_DIR / project_name

    timeline = parse_messages_txt(project_dir / "messages.txt")
    for msg in timeline:
        msg["project"] = project_name

    changes = []
    misalignments = []
    stats = {}

    db_path = project_dir / "events.db"
    if db_path.exists():
        events = get_events(project_name, limit=500)
        for event in events:
            event["project"] = project_name
            if event["event_type"] == "UPDATE":
                changes.append(event)
            elif event["event_type"] in ("MISALIGN", "QUESTION"):
                misalignments.append(event)
        stats[project_name] = build_stats(events)

    timeline.sort(key=lambda x: x["timestamp"])

    _write_json("meta.json", {"project": project_name})
    _write_json("timeline.json", timeline)
    _write_json("changes.json", changes)
    _write_json("misalignments.json", misalignments)
    _write_json("stats.json", stats)

    print(f"Exported {len(timeline)} timeline entries, {len(changes)} changes, {len(misalignments)} misalignments")
    print(f"Project: {project_name}")
    print(f"Output: {DASHBOARD_DIR}/")


def _write_json(filename: str, data: list | dict) -> None:
    path = DASHBOARD_DIR / filename
    path.write_text(json.dumps(data, indent=2))


def deploy(project_name: str) -> str:
    """Export data and deploy to Cloudflare Pages. Returns the deployment URL."""
    export(project_name)
    result = subprocess.run(
        ["npx", "wrangler", "pages", "deploy", "./dashboard",
         "--project-name", "humanand-dashboard", "--commit-dirty=true"],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    log.info("Wrangler output: %s", output)

    # Parse URL from wrangler output
    match = re.search(r"https://[\w.-]+\.pages\.dev", output)
    if match:
        return match.group(0)
    if result.returncode != 0:
        raise RuntimeError(f"Deploy failed: {output}")
    return "https://humanand-dashboard.pages.dev"


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "export":
        export(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "deploy":
        url = deploy(sys.argv[2])
        print(f"Deployed to: {url}")
    else:
        print("Usage: python dashboard.py [export|deploy] <project_name>")
