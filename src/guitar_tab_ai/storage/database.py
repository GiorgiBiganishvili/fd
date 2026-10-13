"""Local SQLite preferences and recent project history."""
import json
import sqlite3
from pathlib import Path


class Preferences:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS recent (path TEXT PRIMARY KEY, opened TEXT NOT NULL)")

    def set(self, key: str, value: object) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO preferences VALUES (?, ?)", (key, json.dumps(value)))

    def get(self, key: str, default: object = None) -> object:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def remember(self, path: Path) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO recent VALUES (?, datetime('now'))", (str(path.resolve()),))

    def recent(self) -> list[str]:
        with sqlite3.connect(self.path) as db:
            return [r[0] for r in db.execute("SELECT path FROM recent ORDER BY opened DESC LIMIT 12")]
