import sqlite3
from datetime import datetime
from pathlib import Path

PROJECTS_DIR = Path("projects")

_connections: dict[str, sqlite3.Connection] = {}

CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    user TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    permalink TEXT NOT NULL,
    reaction TEXT,
    reacted_by TEXT
)
"""


def get_db(project_name: str) -> sqlite3.Connection:
    if project_name in _connections:
        return _connections[project_name]
    db_path = PROJECTS_DIR / project_name / "events.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(CREATE_EVENTS)
    conn.commit()
    _connections[project_name] = conn
    return conn


def log_event(
    project: str,
    event_type: str,
    user: str,
    category: str,
    content: str,
    permalink: str,
) -> int:
    conn = get_db(project)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute(
        "INSERT INTO events (timestamp, event_type, user, category, content, permalink) VALUES (?, ?, ?, ?, ?, ?)",
        (timestamp, event_type, user, category, content, permalink),
    )
    conn.commit()
    return cursor.lastrowid or 0


def update_reaction(project: str, event_id: int, reaction: str, reacted_by: str) -> None:
    conn = get_db(project)
    conn.execute(
        "UPDATE events SET reaction = ?, reacted_by = ? WHERE id = ?",
        (reaction, reacted_by, event_id),
    )
    conn.commit()


def get_events(project: str, limit: int = 50) -> list[dict]:
    conn = get_db(project)
    rows = conn.execute(
        "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]
