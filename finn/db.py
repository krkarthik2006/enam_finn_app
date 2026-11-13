import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio(ticker TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS announcements(
 id TEXT PRIMARY KEY, ticker TEXT NOT NULL, published_at TEXT NOT NULL,
 category TEXT NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS announcements_window ON announcements(mode, published_at, ticker);
CREATE TABLE IF NOT EXISTS prices(
 ticker TEXT NOT NULL, day TEXT NOT NULL, mode TEXT NOT NULL, close REAL NOT NULL,
 volume INTEGER NOT NULL, PRIMARY KEY(ticker,day,mode));
CREATE TABLE IF NOT EXISTS documents(
 id TEXT PRIMARY KEY, ticker TEXT NOT NULL, kind TEXT NOT NULL, mode TEXT NOT NULL,
 title TEXT NOT NULL, url TEXT NOT NULL, published_on TEXT NOT NULL, content_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks(
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, page INTEGER, text TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_cache(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS llm_calls(
 id INTEGER PRIMARY KEY, model TEXT NOT NULL, task TEXT NOT NULL, status TEXT NOT NULL,
 prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL, seconds REAL NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS refresh_runs(
 id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, payload TEXT NOT NULL);
PRAGMA user_version=1;
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def all(self, query, params=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def one(self, query, params=()):
        rows = self.all(query, params)
        return rows[0] if rows else None

    def execute(self, query, params=()):
        with self.connect() as conn:
            conn.execute(query, params)

    def setting(self, key, default):
        row = self.one("SELECT payload FROM settings WHERE key=?", (key,))
        return json.loads(row["payload"]) if row else default

    def set_setting(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
