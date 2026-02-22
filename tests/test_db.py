import tempfile
from pathlib import Path
from unittest.mock import patch

from src.stores.db import get_events, log_event, update_reaction, _connections


def _reset_connections():
    _connections.clear()


def test_log_event_inserts_row():
    _reset_connections()
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.stores.db.PROJECTS_DIR", Path(tmp)):
            event_id = log_event("testproject", "ROUTE", "U123", "escalation", "needs DB help", "https://slack.com/archives/C1/p111")
            assert event_id > 0
            events = get_events("testproject")
    assert len(events) == 1
    assert events[0]["event_type"] == "ROUTE"
    assert events[0]["user"] == "U123"
    assert events[0]["category"] == "escalation"
    assert events[0]["content"] == "needs DB help"
    assert events[0]["reaction"] is None


def test_update_reaction_sets_fields():
    _reset_connections()
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.stores.db.PROJECTS_DIR", Path(tmp)):
            event_id = log_event("testproject", "UPDATE", "U123", "decision", "Switch to Postgres", "https://slack.com/archives/C1/p111")
            update_reaction("testproject", event_id, "approved", "U456")
            events = get_events("testproject")
    assert events[0]["reaction"] == "approved"
    assert events[0]["reacted_by"] == "U456"


def test_multiple_events_ordered_newest_first():
    _reset_connections()
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.stores.db.PROJECTS_DIR", Path(tmp)):
            log_event("testproject", "ROUTE", "U1", "escalation", "first", "link1")
            log_event("testproject", "MISALIGN", "U2", "pivot", "second", "link2")
            events = get_events("testproject")
    assert len(events) == 2
    assert events[0]["content"] == "second"
    assert events[1]["content"] == "first"


def test_separate_projects_have_separate_dbs():
    _reset_connections()
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.stores.db.PROJECTS_DIR", Path(tmp)):
            log_event("project_a", "ROUTE", "U1", "escalation", "from A", "link1")
            log_event("project_b", "UPDATE", "U2", "decision", "from B", "link2")
            events_a = get_events("project_a")
            events_b = get_events("project_b")
    assert len(events_a) == 1
    assert events_a[0]["content"] == "from A"
    assert len(events_b) == 1
    assert events_b[0]["content"] == "from B"


def test_db_file_created_in_project_dir():
    _reset_connections()
    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.stores.db.PROJECTS_DIR", Path(tmp)):
            log_event("testproject", "ROUTE", "U1", "escalation", "test", "link")
        assert (Path(tmp) / "testproject" / "events.db").exists()
