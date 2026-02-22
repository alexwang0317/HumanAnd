import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.services.dashboard_service import build_stats, parse_messages_txt, export


def test_parse_messages_txt():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "messages.txt"
        path.write_text(
            "# Important messages\n"
            "# Format: ...\n"
            "2026-02-21 14:34 | <@U123> | https://slack.com/archives/C1/p111 | decision | Switched to Postgres\n"
            "2026-02-21 15:00 | <@U456> | https://slack.com/archives/C1/p222 | blocker | CI broken\n"
        )
        entries = parse_messages_txt(path)
    assert len(entries) == 2
    assert entries[0]["user"] == "U123"
    assert entries[0]["category"] == "decision"
    assert entries[0]["summary"] == "Switched to Postgres"
    assert entries[1]["category"] == "blocker"


def test_parse_messages_txt_missing_file():
    entries = parse_messages_txt(Path("/nonexistent/messages.txt"))
    assert entries == []


def test_build_stats():
    events = [
        {"event_type": "UPDATE", "category": "decision", "timestamp": "2026-02-21 14:00:00", "reaction": "approved"},
        {"event_type": "MISALIGN", "category": "pivot", "timestamp": "2026-02-21 15:00:00", "reaction": "rejected"},
        {"event_type": "ROUTE", "category": "escalation", "timestamp": "2026-02-22 10:00:00", "reaction": None},
    ]
    stats = build_stats(events)
    assert stats["total_events"] == 3
    assert stats["by_type"]["UPDATE"] == 1
    assert stats["by_type"]["MISALIGN"] == 1
    assert stats["by_type"]["ROUTE"] == 1
    assert stats["total_approved"] == 1
    assert stats["total_with_reaction"] == 2
    assert stats["acceptance_rate"] == 50


def test_build_stats_empty():
    stats = build_stats([])
    assert stats["total_events"] == 0
    assert stats["acceptance_rate"] == 0


def test_export_writes_json_files():
    with tempfile.TemporaryDirectory() as tmp:
        # Create a project with messages.txt
        project_dir = Path(tmp) / "testproject"
        project_dir.mkdir()
        (project_dir / "messages.txt").write_text(
            "# messages\n"
            "2026-02-21 14:34 | <@U123> | https://slack.com/link | decision | test entry\n"
        )

        dashboard_dir = Path(tmp) / "dashboard" / "data"

        with patch("src.services.dashboard_service.PROJECTS_DIR", Path(tmp)):
            with patch("src.services.dashboard_service.DASHBOARD_DIR", dashboard_dir):
                export("testproject")

        assert (dashboard_dir / "meta.json").exists()
        assert (dashboard_dir / "timeline.json").exists()
        assert (dashboard_dir / "changes.json").exists()
        assert (dashboard_dir / "misalignments.json").exists()
        assert (dashboard_dir / "stats.json").exists()

        meta = json.loads((dashboard_dir / "meta.json").read_text())
        assert meta["project"] == "testproject"

        timeline = json.loads((dashboard_dir / "timeline.json").read_text())
        assert len(timeline) == 1
        assert timeline[0]["summary"] == "test entry"
        assert timeline[0]["project"] == "testproject"
