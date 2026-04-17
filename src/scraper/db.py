import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS shows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id TEXT UNIQUE NOT NULL,          -- sha256 of feed_url or platform-specific ID
    name TEXT NOT NULL,
    feed_url TEXT,
    language TEXT DEFAULT 'it',
    description TEXT,
    author TEXT,
    categories TEXT,                        -- JSON array
    episode_count INTEGER DEFAULT 0,
    total_duration_hours REAL DEFAULT 0,
    source TEXT NOT NULL,                   -- 'spreaker', 'podcast_index', 'apple'
    source_id TEXT,                         -- platform-specific ID
    itunes_id TEXT,
    multi_speaker_score REAL DEFAULT 0,     -- 0-1 heuristic score
    discovered_at TEXT DEFAULT (datetime('now')),
    state TEXT DEFAULT 'discovered'         -- discovered, validated, downloading, completed, skipped
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT UNIQUE NOT NULL,        -- sha256 of audio_url
    show_id TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    duration_seconds INTEGER,
    audio_url TEXT NOT NULL,
    audio_format TEXT DEFAULT 'mp3',
    file_size_bytes INTEGER,
    file_path TEXT,                          -- local path after download
    download_state TEXT DEFAULT 'pending',   -- pending, downloading, completed, failed, skipped
    download_error TEXT,
    download_attempts INTEGER DEFAULT 0,
    pass1_state TEXT DEFAULT 'pending',      -- pending, processing, completed, failed
    pass2_state TEXT DEFAULT 'pending',      -- pending, processing, completed, failed
    asr_confidence REAL,
    speakers_detected INTEGER,
    discovered_at TEXT DEFAULT (datetime('now')),
    downloaded_at TEXT,
    FOREIGN KEY (show_id) REFERENCES shows(show_id)
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    action TEXT NOT NULL,                    -- 'search', 'browse', 'lookup'
    query TEXT,
    shows_found INTEGER DEFAULT 0,
    episodes_found INTEGER DEFAULT 0,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_episodes_show ON episodes(show_id);
CREATE INDEX IF NOT EXISTS idx_episodes_download ON episodes(download_state);
CREATE INDEX IF NOT EXISTS idx_episodes_pass1 ON episodes(pass1_state);
CREATE INDEX IF NOT EXISTS idx_shows_state ON shows(state);
CREATE INDEX IF NOT EXISTS idx_shows_source ON shows(source);
"""


class VociDB:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_show(self, show_id: str, name: str, source: str, **kwargs) -> bool:
        """Insert or update a show. Returns True if new, False if updated."""
        existing = self.conn.execute(
            "SELECT id FROM shows WHERE show_id = ?", (show_id,)
        ).fetchone()

        if existing:
            updates = {k: v for k, v in kwargs.items() if v is not None}
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [show_id]
                self.conn.execute(
                    f"UPDATE shows SET {set_clause} WHERE show_id = ?", values
                )
                self.conn.commit()
            return False

        cols = ["show_id", "name", "source"] + [k for k, v in kwargs.items() if v is not None]
        vals = [show_id, name, source] + [v for v in kwargs.values() if v is not None]
        placeholders = ", ".join("?" * len(cols))
        col_str = ", ".join(cols)
        self.conn.execute(f"INSERT INTO shows ({col_str}) VALUES ({placeholders})", vals)
        self.conn.commit()
        return True

    def upsert_episode(self, episode_id: str, show_id: str, audio_url: str, **kwargs) -> bool:
        """Insert or update an episode. Returns True if new."""
        existing = self.conn.execute(
            "SELECT id FROM episodes WHERE episode_id = ?", (episode_id,)
        ).fetchone()

        if existing:
            return False

        cols = ["episode_id", "show_id", "audio_url"] + [k for k, v in kwargs.items() if v is not None]
        vals = [episode_id, show_id, audio_url] + [v for v in kwargs.values() if v is not None]
        placeholders = ", ".join("?" * len(cols))
        col_str = ", ".join(cols)
        self.conn.execute(f"INSERT INTO episodes ({col_str}) VALUES ({placeholders})", vals)
        self.conn.commit()
        return True

    def log_scrape(self, source: str, action: str, query: str = None,
                   shows_found: int = 0, episodes_found: int = 0):
        self.conn.execute(
            "INSERT INTO scrape_log (source, action, query, shows_found, episodes_found) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, action, query, shows_found, episodes_found)
        )
        self.conn.commit()

    def get_pending_downloads(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT e.*, s.name as show_name FROM episodes e "
            "JOIN shows s ON e.show_id = s.show_id "
            "WHERE e.download_state = 'pending' "
            "ORDER BY e.discovered_at "
            "LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_episode_state(self, episode_id: str, **kwargs):
        updates = {k: v for k, v in kwargs.items() if v is not None}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [episode_id]
        self.conn.execute(
            f"UPDATE episodes SET {set_clause} WHERE episode_id = ?", values
        )
        self.conn.commit()

    def update_show_state(self, show_id: str, state: str):
        self.conn.execute(
            "UPDATE shows SET state = ? WHERE show_id = ?", (state, show_id)
        )
        self.conn.commit()

    def get_stats(self) -> dict:
        stats = {}
        row = self.conn.execute("SELECT COUNT(*) as c FROM shows").fetchone()
        stats["total_shows"] = row["c"]

        row = self.conn.execute("SELECT COUNT(*) as c FROM episodes").fetchone()
        stats["total_episodes"] = row["c"]

        row = self.conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) / 3600.0 as h FROM episodes"
        ).fetchone()
        stats["total_hours"] = round(row["h"], 1)

        for state in ["pending", "downloading", "completed", "failed"]:
            row = self.conn.execute(
                "SELECT COUNT(*) as c FROM episodes WHERE download_state = ?", (state,)
            ).fetchone()
            stats[f"download_{state}"] = row["c"]

        row = self.conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) / 3600.0 as h "
            "FROM episodes WHERE download_state = 'completed'"
        ).fetchone()
        stats["downloaded_hours"] = round(row["h"], 1)

        return stats

    def get_show_ids_by_source(self, source: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT source_id FROM shows WHERE source = ? AND source_id IS NOT NULL",
            (source,)
        ).fetchall()
        return {r["source_id"] for r in rows}

    def get_all_feed_urls(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT feed_url FROM shows WHERE feed_url IS NOT NULL"
        ).fetchall()
        return {r["feed_url"] for r in rows}

    def close(self):
        self.conn.close()
