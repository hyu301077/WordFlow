"""SQLite 连接与迁移。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from wordflow.settings import DEFAULTS
from wordflow.timeutil import now_local, to_iso

SCHEMA_VERSION = 3

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY,
    lemma TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display TEXT NOT NULL,
    phonetic TEXT,
    phonetic_source TEXT NOT NULL DEFAULT 'missing',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS senses (
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    pos TEXT NOT NULL DEFAULT '',
    gloss_zh TEXT NOT NULL,
    gloss_en TEXT,
    source TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    path TEXT,
    path_key TEXT UNIQUE,
    tags TEXT NOT NULL DEFAULT '',
    content TEXT,
    file_size INTEGER,
    mtime_ns INTEGER,
    fingerprint TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    error_message TEXT,
    word_count INTEGER NOT NULL DEFAULT 0,
    unique_count INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS word_occurrences (
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    surface TEXT NOT NULL,
    frequency INTEGER NOT NULL DEFAULT 1,
    UNIQUE(word_id, document_id, surface)
);

CREATE TABLE IF NOT EXISTS examples (
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    sentence TEXT NOT NULL,
    translation TEXT,
    source TEXT NOT NULL DEFAULT 'document'
);

CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deck_words (
    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    PRIMARY KEY (deck_id, word_id)
);

CREATE TABLE IF NOT EXISTS learning_states (
    word_id INTEGER PRIMARY KEY REFERENCES words(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    mastery INTEGER NOT NULL DEFAULT 0,
    ease REAL NOT NULL DEFAULT 2.5,
    interval_days REAL NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    skip_count INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    next_review_at TEXT,
    last_review_at TEXT,
    last_learned_at TEXT,
    manual_override INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT '',
    document_id INTEGER,
    deck_id INTEGER,
    status TEXT NOT NULL,
    cursor_index INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS session_items (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    sense_id INTEGER,
    position INTEGER NOT NULL,
    prompt_pos TEXT,
    correct_gloss TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL DEFAULT '[]',
    example TEXT,
    answer TEXT,
    result TEXT,
    rating TEXT,
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS review_logs (
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    session_id INTEGER,
    mode TEXT NOT NULL,
    rating TEXT NOT NULL,
    correct INTEGER,
    chosen_gloss TEXT,
    correct_gloss TEXT,
    ease_before REAL,
    ease_after REAL,
    interval_before REAL,
    interval_after REAL,
    next_review_at TEXT,
    day TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_stats (
    day TEXT PRIMARY KEY,
    studied INTEGER NOT NULL DEFAULT 0,
    new_learned INTEGER NOT NULL DEFAULT 0,
    reviewed INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    wrong INTEGER NOT NULL DEFAULT 0,
    mastered_total INTEGER NOT NULL DEFAULT 0,
    learning_total INTEGER NOT NULL DEFAULT 0,
    untested_total INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_senses_word ON senses(word_id);
CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(kind, status);
CREATE INDEX IF NOT EXISTS idx_documents_fp ON documents(fingerprint);
CREATE INDEX IF NOT EXISTS idx_occ_doc ON word_occurrences(document_id);
CREATE INDEX IF NOT EXISTS idx_occ_word ON word_occurrences(word_id);
CREATE INDEX IF NOT EXISTS idx_examples_word ON examples(word_id);
CREATE INDEX IF NOT EXISTS idx_learning_status ON learning_states(status);
CREATE INDEX IF NOT EXISTS idx_learning_due ON learning_states(next_review_at);
CREATE INDEX IF NOT EXISTS idx_items_session ON session_items(session_id, position);
CREATE INDEX IF NOT EXISTS idx_review_word ON review_logs(word_id, created_at);
CREATE INDEX IF NOT EXISTS idx_review_day ON review_logs(day);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 8000")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    version = row[0] or 0
    if version < 1:
        connection.executescript(SCHEMA_V1)
        _seed(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (to_iso(now_local()),),
        )
        version = 1
    if version < 2:
        _migrate_v2(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (2, ?)",
            (to_iso(now_local()),),
        )
        version = 2
    if version < 3:
        _migrate_v3(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (3, ?)",
            (to_iso(now_local()),),
        )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _migrate_v2(connection: sqlite3.Connection) -> None:
    _add_column(connection, "learning_states", "stability", "REAL NOT NULL DEFAULT 0")
    _add_column(connection, "learning_states", "difficulty", "REAL NOT NULL DEFAULT 0")
    _add_column(connection, "learning_states", "fsrs_state", "TEXT NOT NULL DEFAULT 'new'")
    _add_column(connection, "learning_states", "fsrs_step", "INTEGER NOT NULL DEFAULT 0")
    connection.execute(
        """
        UPDATE learning_states
        SET stability = CASE WHEN interval_days > 0 THEN interval_days ELSE 0 END,
            difficulty = 5,
            fsrs_state = CASE
                WHEN status IN ('mastered', 'reviewing') THEN 'review'
                WHEN status = 'learning' THEN 'learning'
                ELSE 'new'
            END,
            fsrs_step = 0
        WHERE status IN ('mastered', 'reviewing', 'learning')
          AND stability = 0
          AND fsrs_state = 'new'
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_records (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            word_id INTEGER,
            title TEXT NOT NULL DEFAULT '',
            request_preview TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ai_records_created ON ai_records(created_at)")


def _migrate_v3(connection: sqlite3.Connection) -> None:
    _add_column(connection, "learning_states", "leech", "INTEGER NOT NULL DEFAULT 0")
    _add_column(connection, "review_logs", "state_before_json", "TEXT")
    _add_column(connection, "review_logs", "undone", "INTEGER NOT NULL DEFAULT 0")


def _add_column(connection: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _seed(connection: sqlite3.Connection) -> None:
    now = to_iso(now_local())
    connection.execute(
        """
        INSERT INTO decks(name, description, is_default, created_at)
        VALUES ('默认词库', '导入和手动添加的单词默认进入这个词库', 1, ?)
        """,
        (now,),
    )
    connection.executemany(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        list(DEFAULTS.items()),
    )
