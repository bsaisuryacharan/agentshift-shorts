import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(data_dir / "shorts_factory.sqlite3")
        self.db.execute("""CREATE TABLE IF NOT EXISTS approved_runs (
          run_id TEXT PRIMARY KEY, title TEXT NOT NULL, script TEXT NOT NULL,
          video_path TEXT, created_at TEXT NOT NULL)""")
        # A topic can be factually excellent but unusable for an automatic Short: for example,
        # an official article may provide only one still image. Keep that operational outcome so
        # the next autonomous cycle chooses another source instead of repeating the same failure.
        self.db.execute("""CREATE TABLE IF NOT EXISTS rejected_sources (
          source_url TEXT PRIMARY KEY, title TEXT NOT NULL, reason TEXT NOT NULL,
          rejected_at TEXT NOT NULL)""")
        self.db.commit()

    def recent_scripts(self, limit: int = 30) -> list[str]:
        return [r[0] for r in self.db.execute(
            "SELECT script FROM approved_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )]

    def approved_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM approved_runs").fetchone()[0])

    def save_approved(self, run_id: str, title: str, script: str, video_path: str, created_at: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO approved_runs VALUES (?, ?, ?, ?, ?)",
                        (run_id, title, script, video_path, created_at))
        self.db.commit()

    def rejected_source_urls(self, limit: int = 100) -> set[str]:
        return {row[0] for row in self.db.execute(
            # Asset-policy upgrades may make a source usable without invalidating its recorded
            # audit trail.  Legacy asset rejections are retried once under the current policy;
            # current-policy rejections and all editorial/visual rejections remain excluded.
            "SELECT source_url FROM rejected_sources "
            "WHERE reason NOT LIKE 'Source-asset gate:%' OR reason LIKE 'Source-asset gate v2:%' "
            "ORDER BY rejected_at DESC LIMIT ?", (limit,)
        )}

    def save_source_rejection(self, source_url: str, title: str, reason: str, rejected_at: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO rejected_sources VALUES (?, ?, ?, ?)",
            (source_url, title, reason, rejected_at),
        )
        self.db.commit()

    @staticmethod
    def write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
