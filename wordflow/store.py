"""全部持久化操作。写入默认自动成事务，扫描时可以包在同一个事务里。"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from pathlib import Path

from wordflow.constants import NEW_WORD_STATUSES, STATUS_MASTERED, STATUS_UNTESTED
from wordflow.db import connect, migrate
from wordflow.srs import MemoryState, state_from_dict, state_to_dict
from wordflow.timeutil import from_iso, now_local, today_str, to_iso

_SORTS = {
    "alpha": "w.lemma COLLATE NOCASE ASC",
    "time": "s.updated_at DESC",
    "freq": "freq DESC, w.lemma COLLATE NOCASE ASC",
    "wrong": "s.wrong_count DESC, w.lemma COLLATE NOCASE ASC",
    "mastery": "s.mastery ASC, w.lemma COLLATE NOCASE ASC",
    "due": "CASE WHEN s.next_review_at IS NULL THEN 1 ELSE 0 END, s.next_review_at ASC",
}


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = connect(self.path)
        self._tx_depth = 0
        migrate(self.conn)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self):
        self._tx_depth += 1
        try:
            if self._tx_depth == 1:
                self.conn.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            if self._tx_depth == 1:
                self.conn.rollback()
            raise
        else:
            if self._tx_depth == 1:
                self.conn.commit()
        finally:
            self._tx_depth -= 1

    def _guard(self):
        if self._tx_depth == 0:
            return self.tx()
        return nullcontext()

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(row) for row in self.conn.execute(sql, params)]

    def _one(self, sql: str, params: tuple = ()) -> dict | None:
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all_settings(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self.conn.execute("SELECT key, value FROM settings")}

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._guard():
            self.conn.execute(
                """
                INSERT INTO settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def list_decks(self) -> list[dict]:
        return self._all("SELECT * FROM decks ORDER BY is_default DESC, name COLLATE NOCASE")

    def get_default_deck_id(self) -> int:
        row = self._one("SELECT id FROM decks WHERE is_default = 1 ORDER BY id LIMIT 1")
        if row:
            return int(row["id"])
        row = self._one("SELECT id FROM decks ORDER BY id LIMIT 1")
        if row:
            return int(row["id"])
        now = to_iso(now_local())
        with self._guard():
            cursor = self.conn.execute(
                "INSERT INTO decks(name, description, is_default, created_at) VALUES ('默认词库', '', 1, ?)",
                (now,),
            )
            return int(cursor.lastrowid)

    def create_deck(self, name: str, description: str = "") -> int:
        with self._guard():
            cursor = self.conn.execute(
                "INSERT INTO decks(name, description, is_default, created_at) VALUES (?, ?, 0, ?)",
                (name.strip(), description.strip(), to_iso(now_local())),
            )
            return int(cursor.lastrowid)

    def rename_deck(self, deck_id: int, name: str) -> None:
        with self._guard():
            self.conn.execute("UPDATE decks SET name = ? WHERE id = ? AND is_default = 0", (name.strip(), deck_id))

    def delete_deck(self, deck_id: int) -> None:
        with self._guard():
            self.conn.execute("DELETE FROM decks WHERE id = ? AND is_default = 0", (deck_id,))

    def set_word_decks(self, word_id: int, deck_ids: list[int]) -> None:
        with self._guard():
            self.conn.execute("DELETE FROM deck_words WHERE word_id = ?", (word_id,))
            now = to_iso(now_local())
            self.conn.executemany(
                "INSERT OR IGNORE INTO deck_words(deck_id, word_id, added_at) VALUES (?, ?, ?)",
                [(deck_id, word_id, now) for deck_id in deck_ids],
            )

    def add_words_to_deck(self, deck_id: int, word_ids: list[int]) -> None:
        with self._guard():
            now = to_iso(now_local())
            self.conn.executemany(
                "INSERT OR IGNORE INTO deck_words(deck_id, word_id, added_at) VALUES (?, ?, ?)",
                [(deck_id, word_id, now) for word_id in word_ids],
            )

    def word_deck_ids(self, word_id: int) -> list[int]:
        rows = self._all("SELECT deck_id FROM deck_words WHERE word_id = ? ORDER BY deck_id", (word_id,))
        return [int(row["deck_id"]) for row in rows]

    def get_document_by_path(self, path_key: str) -> dict | None:
        return self._one("SELECT * FROM documents WHERE path_key = ?", (path_key,))

    def get_document_by_fingerprint(self, fingerprint: str) -> dict | None:
        return self._one(
            "SELECT * FROM documents WHERE fingerprint = ? ORDER BY id LIMIT 1",
            (fingerprint,),
        )

    def get_document(self, document_id: int) -> dict | None:
        return self._one("SELECT * FROM documents WHERE id = ?", (document_id,))

    def list_study_plans(self) -> list[dict]:
        return self._all(
            "SELECT * FROM documents WHERE study_plan = 1 ORDER BY updated_at DESC, id DESC"
        )

    def set_study_plan(self, document_id: int, enabled: bool = True) -> None:
        with self._guard():
            self.conn.execute(
                "UPDATE documents SET study_plan = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, to_iso(now_local()), document_id),
            )

    def list_documents(self, kind: str | None = None) -> list[dict]:
        if kind:
            return self._all(
                "SELECT * FROM documents WHERE kind = ? ORDER BY updated_at DESC, id DESC",
                (kind,),
            )
        return self._all("SELECT * FROM documents ORDER BY updated_at DESC, id DESC")

    def upsert_document(self, fields: dict) -> int:
        with self._guard():
            existing = None
            if fields.get("path_key"):
                existing = self.get_document_by_path(fields["path_key"])
            if existing:
                title = fields["title"]
                if int(existing["study_plan"] or 0) and str(existing["title"] or "").strip():
                    title = existing["title"]
                self.conn.execute(
                    """
                    UPDATE documents
                    SET title = ?, kind = ?, path = ?, tags = COALESCE(?, tags), content = ?,
                        file_size = ?, mtime_ns = ?, fingerprint = ?, status = ?, error_message = ?,
                        word_count = ?, unique_count = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        fields.get("kind", existing["kind"]),
                        fields.get("path"),
                        fields.get("tags"),
                        fields.get("content"),
                        fields.get("file_size"),
                        fields.get("mtime_ns"),
                        fields.get("fingerprint"),
                        fields.get("status", "active"),
                        fields.get("error_message"),
                        fields.get("word_count", 0),
                        fields.get("unique_count", 0),
                        fields["updated_at"],
                        existing["id"],
                    ),
                )
                return int(existing["id"])
            cursor = self.conn.execute(
                """
                INSERT INTO documents (
                    kind, title, path, path_key, tags, content, file_size, mtime_ns,
                    fingerprint, status, error_message, word_count, unique_count,
                    imported_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["kind"],
                    fields["title"],
                    fields.get("path"),
                    fields.get("path_key"),
                    fields.get("tags") or "",
                    fields.get("content"),
                    fields.get("file_size"),
                    fields.get("mtime_ns"),
                    fields.get("fingerprint"),
                    fields.get("status", "active"),
                    fields.get("error_message"),
                    fields.get("word_count", 0),
                    fields.get("unique_count", 0),
                    fields["imported_at"],
                    fields["updated_at"],
                ),
            )
            return int(cursor.lastrowid)

    def touch_document(self, document_id: int, file_size: int, mtime_ns: int) -> None:
        with self._guard():
            self.conn.execute(
                "UPDATE documents SET file_size = ?, mtime_ns = ?, updated_at = ? WHERE id = ?",
                (file_size, mtime_ns, to_iso(now_local()), document_id),
            )

    def update_document_meta(self, document_id: int, title: str, tags: str) -> None:
        with self._guard():
            self.conn.execute(
                "UPDATE documents SET title = ?, tags = ?, updated_at = ? WHERE id = ?",
                (title.strip(), tags.strip(), to_iso(now_local()), document_id),
            )

    def clear_document_links(self, document_id: int) -> None:
        with self._guard():
            self.conn.execute("DELETE FROM word_occurrences WHERE document_id = ?", (document_id,))
            self.conn.execute("DELETE FROM examples WHERE document_id = ?", (document_id,))

    def mark_document_missing(self, document_id: int) -> None:
        with self._guard():
            self.clear_document_links(document_id)
            self.conn.execute(
                "UPDATE documents SET status = 'missing', updated_at = ? WHERE id = ?",
                (to_iso(now_local()), document_id),
            )

    def delete_document(self, document_id: int) -> None:
        with self._guard():
            self.conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    def document_status_map(self, document_id: int) -> dict[str, str]:
        rows = self._all(
            """
            SELECT DISTINCT w.lemma, s.status
            FROM word_occurrences o
            JOIN words w ON w.id = o.word_id
            JOIN learning_states s ON s.word_id = w.id
            WHERE o.document_id = ?
            """,
            (document_id,),
        )
        return {row["lemma"]: row["status"] for row in rows}

    def document_word_ids(self, document_id: int) -> list[int]:
        rows = self._all(
            "SELECT DISTINCT word_id FROM word_occurrences WHERE document_id = ? ORDER BY word_id",
            (document_id,),
        )
        return [int(row["word_id"]) for row in rows]

    def coverage(self, document_id: int) -> dict:
        row = self._one(
            """
            SELECT
                COUNT(*) AS unique_count,
                SUM(CASE WHEN s.status = 'mastered' THEN 1 ELSE 0 END) AS mastered,
                SUM(CASE WHEN s.status IN ('learning', 'reviewing') THEN 1 ELSE 0 END) AS learning,
                SUM(CASE WHEN s.status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN s.status = 'untested' THEN 1 ELSE 0 END) AS untested
            FROM (
                SELECT DISTINCT word_id FROM word_occurrences WHERE document_id = ?
            ) occ
            JOIN learning_states s ON s.word_id = occ.word_id
            """,
            (document_id,),
        )
        return row or {"unique_count": 0, "mastered": 0, "learning": 0, "pending": 0, "untested": 0}

    def document_words(self, document_id: int) -> list[dict]:
        return self._document_word_rows(document_id, None)

    def top_document_words(self, document_id: int, limit: int = 30) -> list[dict]:
        return self._document_word_rows(document_id, limit)

    def _document_word_rows(self, document_id: int, limit: int | None) -> list[dict]:
        sql = """
            SELECT w.id, w.lemma, w.phonetic, s.status, s.mastery,
                   SUM(o.frequency) AS frequency,
                   (SELECT gloss_zh FROM senses se WHERE se.word_id = w.id
                    ORDER BY se.is_primary DESC, se.sort_order, se.id LIMIT 1) AS gloss
            FROM word_occurrences o
            JOIN words w ON w.id = o.word_id
            JOIN learning_states s ON s.word_id = w.id
            WHERE o.document_id = ?
            GROUP BY w.id
            ORDER BY frequency DESC, w.lemma
        """
        params: list = [document_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return self._all(sql, tuple(params))

    def ensure_word(self, lemma: str, display: str, entry) -> int:
        with self._guard():
            lemma = lemma.strip().lower()
            row = self._one("SELECT * FROM words WHERE lemma = ? COLLATE NOCASE", (lemma,))
            now = to_iso(now_local())
            if row:
                word_id = int(row["id"])
                if entry and entry.phonetic and not row["phonetic"] and row["phonetic_source"] != "manual":
                    self.conn.execute(
                        """
                        UPDATE words
                        SET phonetic = ?, phonetic_source = 'dictionary', updated_at = ?
                        WHERE id = ?
                        """,
                        (entry.phonetic, now, word_id),
                    )
                if entry and entry.senses and self._sense_count(word_id) == 0:
                    self._insert_dictionary_senses(word_id, entry)
                self._ensure_state(word_id)
                self._link_default_deck(word_id)
                return word_id
            phonetic = entry.phonetic if entry and entry.phonetic else None
            source = "dictionary" if phonetic else "missing"
            cursor = self.conn.execute(
                """
                INSERT INTO words(lemma, display, phonetic, phonetic_source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (lemma, display or lemma, phonetic, source, now, now),
            )
            word_id = int(cursor.lastrowid)
            if entry and entry.senses:
                self._insert_dictionary_senses(word_id, entry)
            self._ensure_state(word_id)
            self._link_default_deck(word_id)
            return word_id

    def _sense_count(self, word_id: int) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM senses WHERE word_id = ?", (word_id,)).fetchone()[0])

    def _insert_dictionary_senses(self, word_id: int, entry) -> None:
        for index, sense in enumerate(entry.senses):
            self.conn.execute(
                """
                INSERT INTO senses(word_id, pos, gloss_zh, gloss_en, source, is_primary, sort_order)
                VALUES (?, ?, ?, ?, 'dictionary', ?, ?)
                """,
                (word_id, sense.pos or "", sense.gloss_zh, sense.gloss_en or None, 1 if index == 0 else 0, index),
            )

    def _ensure_state(self, word_id: int) -> None:
        exists = self.conn.execute("SELECT 1 FROM learning_states WHERE word_id = ?", (word_id,)).fetchone()
        if exists:
            return
        self.conn.execute(
            """
            INSERT INTO learning_states(word_id, status, updated_at)
            VALUES (?, ?, ?)
            """,
            (word_id, STATUS_UNTESTED, to_iso(now_local())),
        )

    def _link_default_deck(self, word_id: int) -> None:
        deck_id = self.get_default_deck_id()
        self.conn.execute(
            "INSERT OR IGNORE INTO deck_words(deck_id, word_id, added_at) VALUES (?, ?, ?)",
            (deck_id, word_id, to_iso(now_local())),
        )

    def add_occurrence(self, word_id: int, document_id: int, surface: str, frequency: int) -> None:
        with self._guard():
            self.conn.execute(
                """
                INSERT INTO word_occurrences(word_id, document_id, surface, frequency)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(word_id, document_id, surface)
                DO UPDATE SET frequency = excluded.frequency
                """,
                (word_id, document_id, surface, frequency),
            )

    def add_example(self, word_id: int, document_id: int | None, sentence: str, source: str = "document") -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        with self._guard():
            exists = self._one(
                """
                SELECT id FROM examples
                WHERE word_id = ? AND sentence = ? AND IFNULL(document_id, -1) = IFNULL(?, -1)
                """,
                (word_id, sentence, document_id),
            )
            if exists:
                return
            self.conn.execute(
                """
                INSERT INTO examples(word_id, document_id, sentence, source)
                VALUES (?, ?, ?, ?)
                """,
                (word_id, document_id, sentence, source),
            )

    def get_word(self, word_id: int) -> dict | None:
        return self._one("SELECT * FROM words WHERE id = ?", (word_id,))

    def get_word_by_lemma(self, lemma: str) -> dict | None:
        return self._one("SELECT * FROM words WHERE lemma = ? COLLATE NOCASE", (lemma.strip().lower(),))

    def senses_of(self, word_id: int) -> list[dict]:
        return self._all(
            "SELECT * FROM senses WHERE word_id = ? ORDER BY is_primary DESC, sort_order, id",
            (word_id,),
        )

    def examples_of(self, word_id: int, document_id: int | None = None) -> list[dict]:
        if document_id:
            rows = self._all(
                "SELECT * FROM examples WHERE word_id = ? AND document_id = ? ORDER BY id",
                (word_id, document_id),
            )
            if rows:
                return rows
        return self._all("SELECT * FROM examples WHERE word_id = ? ORDER BY id DESC LIMIT 5", (word_id,))

    def sources_of(self, word_id: int) -> list[dict]:
        return self._all(
            """
            SELECT d.id AS document_id, d.title, d.path, o.surface, o.frequency
            FROM word_occurrences o
            JOIN documents d ON d.id = o.document_id
            WHERE o.word_id = ?
            ORDER BY o.frequency DESC, d.title
            """,
            (word_id,),
        )

    def frequency_of(self, word_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(frequency), 0) FROM word_occurrences WHERE word_id = ?",
            (word_id,),
        ).fetchone()
        return int(row[0])

    def word_detail(self, word_id: int) -> dict | None:
        word = self.get_word(word_id)
        if not word:
            return None
        state = self._one("SELECT * FROM learning_states WHERE word_id = ?", (word_id,))
        errors = self._all(
            """
            SELECT * FROM review_logs
            WHERE word_id = ? AND correct = 0
            ORDER BY created_at DESC LIMIT 20
            """,
            (word_id,),
        )
        return {
            "word": word,
            "senses": self.senses_of(word_id),
            "state": state,
            "examples": self.examples_of(word_id),
            "sources": self.sources_of(word_id),
            "errors": errors,
            "decks": self.word_deck_ids(word_id),
            "frequency": self.frequency_of(word_id),
        }

    def load_state(self, word_id: int) -> MemoryState:
        self._ensure_state(word_id)
        row = self._one("SELECT * FROM learning_states WHERE word_id = ?", (word_id,))
        assert row is not None
        return MemoryState(
            status=row["status"],
            mastery=row["mastery"],
            ease=row["ease"],
            interval_days=row["interval_days"],
            repetitions=row["repetitions"],
            lapses=row["lapses"],
            correct_count=row["correct_count"],
            wrong_count=row["wrong_count"],
            skip_count=row["skip_count"],
            streak=row["streak"],
            next_review_at=from_iso(row["next_review_at"]),
            last_review_at=from_iso(row["last_review_at"]),
            last_learned_at=from_iso(row["last_learned_at"]),
            manual_override=row["manual_override"],
            notes=row["notes"] or "",
            stability=row["stability"] or 0,
            difficulty=row["difficulty"] or 0,
            fsrs_state=row["fsrs_state"] or "new",
            fsrs_step=row["fsrs_step"] or 0,
            leech=row["leech"] or 0,
        )

    def save_state(self, word_id: int, state: MemoryState) -> None:
        with self._guard():
            self.conn.execute(
                """
                UPDATE learning_states SET
                    status = ?, mastery = ?, ease = ?, interval_days = ?, repetitions = ?,
                    lapses = ?, correct_count = ?, wrong_count = ?, skip_count = ?, streak = ?,
                    next_review_at = ?, last_review_at = ?, last_learned_at = ?,
                    manual_override = ?, notes = ?, updated_at = ?,
                    stability = ?, difficulty = ?, fsrs_state = ?, fsrs_step = ?, leech = ?
                WHERE word_id = ?
                """,
                (
                    state.status,
                    int(state.mastery),
                    float(state.ease),
                    float(state.interval_days),
                    int(state.repetitions),
                    int(state.lapses),
                    int(state.correct_count),
                    int(state.wrong_count),
                    int(state.skip_count),
                    int(state.streak),
                    to_iso(state.next_review_at),
                    to_iso(state.last_review_at),
                    to_iso(state.last_learned_at),
                    int(state.manual_override),
                    state.notes,
                    to_iso(now_local()),
                    float(state.stability),
                    float(state.difficulty),
                    state.fsrs_state or "new",
                    int(state.fsrs_step),
                    int(state.leech),
                    word_id,
                ),
            )

    def add_ai_record(
        self,
        *,
        kind: str,
        title: str,
        preview: str,
        content: str,
        model: str,
        word_id: int | None = None,
    ) -> int:
        with self._guard():
            cursor = self.conn.execute(
                """
                INSERT INTO ai_records(kind, word_id, title, request_preview, content, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (kind, word_id, title[:200], preview[:500], content, model[:120], to_iso(now_local())),
            )
            return int(cursor.lastrowid)

    def recent_ai_records(self, limit: int = 30) -> list[dict]:
        return self._all(
            """
            SELECT id, kind, word_id, title, request_preview, content, model, created_at
            FROM ai_records
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def replace_senses(self, word_id: int, senses: list[dict]) -> None:
        with self._guard():
            self.conn.execute("DELETE FROM senses WHERE word_id = ?", (word_id,))
            for index, sense in enumerate(senses):
                gloss = (sense.get("gloss_zh") or "").strip()
                if not gloss:
                    continue
                self.conn.execute(
                    """
                    INSERT INTO senses(word_id, pos, gloss_zh, gloss_en, source, is_primary, sort_order)
                    VALUES (?, ?, ?, ?, 'manual', ?, ?)
                    """,
                    (
                        word_id,
                        (sense.get("pos") or "").strip(),
                        gloss,
                        (sense.get("gloss_en") or "").strip() or None,
                        1 if sense.get("is_primary") else 0,
                        index,
                    ),
                )
            primary = self.conn.execute(
                "SELECT id FROM senses WHERE word_id = ? AND is_primary = 1 ORDER BY id LIMIT 1",
                (word_id,),
            ).fetchone()
            if primary is None:
                first = self.conn.execute(
                    "SELECT id FROM senses WHERE word_id = ? ORDER BY id LIMIT 1",
                    (word_id,),
                ).fetchone()
                if first:
                    self.conn.execute("UPDATE senses SET is_primary = 1 WHERE id = ?", (first["id"],))

    def update_phonetic(self, word_id: int, phonetic: str | None, source: str) -> None:
        with self._guard():
            self.conn.execute(
                "UPDATE words SET phonetic = ?, phonetic_source = ?, updated_at = ? WHERE id = ?",
                (phonetic or None, source, to_iso(now_local()), word_id),
            )

    def update_display(self, word_id: int, display: str) -> None:
        with self._guard():
            self.conn.execute(
                "UPDATE words SET display = ?, updated_at = ? WHERE id = ?",
                (display, to_iso(now_local()), word_id),
            )

    def delete_words(self, word_ids: list[int]) -> None:
        if not word_ids:
            return
        with self._guard():
            self.conn.executemany("DELETE FROM words WHERE id = ?", [(word_id,) for word_id in word_ids])

    def delete_untouched_orphans(self) -> int:
        with self._guard():
            cursor = self.conn.execute(
                """
                DELETE FROM words
                WHERE id NOT IN (SELECT word_id FROM word_occurrences)
                  AND id NOT IN (SELECT word_id FROM review_logs)
                  AND id NOT IN (SELECT word_id FROM session_items)
                  AND id NOT IN (SELECT word_id FROM senses WHERE source = 'manual')
                  AND id IN (
                      SELECT word_id FROM learning_states
                      WHERE status = 'untested' AND IFNULL(notes, '') = ''
                  )
                """
            )
            return cursor.rowcount

    def list_words(
        self,
        *,
        statuses: tuple[str, ...] | None = None,
        query: str = "",
        document_id: int | None = None,
        deck_id: int | None = None,
        mistakes_only: bool = False,
        leeches_only: bool = False,
        sort: str = "alpha",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        where = ["1 = 1"]
        params: list = []
        if statuses:
            marks = ",".join("?" for _ in statuses)
            where.append(f"s.status IN ({marks})")
            params.extend(statuses)
        if mistakes_only:
            where.append("s.wrong_count > 0")
        if leeches_only:
            where.append("s.leech = 1")
        if document_id:
            where.append("w.id IN (SELECT word_id FROM word_occurrences WHERE document_id = ?)")
            params.append(document_id)
        if deck_id:
            where.append("w.id IN (SELECT word_id FROM deck_words WHERE deck_id = ?)")
            params.append(deck_id)
        if query.strip():
            like = f"%{query.strip()}%"
            where.append(
                """(
                    w.lemma LIKE ? OR w.display LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM senses se WHERE se.word_id = w.id AND se.gloss_zh LIKE ?
                    )
                )"""
            )
            params.extend([like, like, like])
        clause = " AND ".join(where)
        order = _SORTS.get(sort, _SORTS["alpha"])
        total = int(
            self.conn.execute(
                f"""
                SELECT COUNT(*)
                FROM words w JOIN learning_states s ON s.word_id = w.id
                WHERE {clause}
                """,
                params,
            ).fetchone()[0]
        )
        rows = self._all(
            f"""
            SELECT w.id, w.lemma, w.display, w.phonetic, w.phonetic_source,
                   s.status, s.mastery, s.wrong_count, s.next_review_at, s.updated_at,
                   (SELECT gloss_zh FROM senses se WHERE se.word_id = w.id
                    ORDER BY se.is_primary DESC, se.sort_order, se.id LIMIT 1) AS gloss,
                   (SELECT COALESCE(SUM(frequency), 0) FROM word_occurrences o WHERE o.word_id = w.id) AS freq
            FROM words w
            JOIN learning_states s ON s.word_id = w.id
            WHERE {clause}
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )
        return rows, total

    def pick_word_ids(
        self,
        *,
        purpose: str,
        limit: int,
        document_id: int | None = None,
        deck_id: int | None = None,
        include_pending: bool = True,
        word_ids: list[int] | None = None,
    ) -> list[int]:
        if word_ids:
            return word_ids[:limit] if limit else list(word_ids)
        filters = ["1 = 1"]
        params: list = []
        if document_id:
            filters.append("w.id IN (SELECT word_id FROM word_occurrences WHERE document_id = ?)")
            params.append(document_id)
        if deck_id:
            filters.append("w.id IN (SELECT word_id FROM deck_words WHERE deck_id = ?)")
            params.append(deck_id)
        now = to_iso(now_local())
        if purpose == "untested":
            statuses = [STATUS_UNTESTED]
            if include_pending:
                statuses.append("pending")
            marks = ",".join("?" for _ in statuses)
            filters.append(f"s.status IN ({marks})")
            params.extend(statuses)
            order = "freq DESC, w.lemma"
        elif purpose == "new" and document_id:
            filters.append("s.status != 'mastered'")
            filters.append("s.last_learned_at IS NULL")
            order = "freq DESC, CASE WHEN s.mastery = 0 THEN 0 ELSE 1 END, s.mastery ASC, w.lemma"
        elif purpose == "new":
            marks = ",".join("?" for _ in NEW_WORD_STATUSES)
            filters.append(f"s.status IN ({marks})")
            params.extend(NEW_WORD_STATUSES)
            filters.append("s.last_learned_at IS NULL")
            order = "CASE WHEN s.mastery = 0 THEN 0 ELSE 1 END, s.mastery ASC, freq DESC"
        elif purpose == "due":
            filters.append("s.next_review_at IS NOT NULL AND s.next_review_at <= ?")
            params.append(now)
            order = "s.leech DESC, CASE WHEN s.status = 'mastered' THEN 1 ELSE 0 END, s.wrong_count DESC, s.next_review_at ASC"
        elif purpose == "mistakes":
            filters.append("s.wrong_count > 0")
            filters.append("s.status != 'mastered'")
            order = "s.leech DESC, s.wrong_count DESC, freq DESC"
        else:
            raise ValueError(purpose)
        clause = " AND ".join(filters)
        if purpose == "new" and document_id:
            freq_sql = """
                (SELECT COALESCE(SUM(frequency), 0) FROM word_occurrences o
                 WHERE o.word_id = w.id AND o.document_id = ?) AS freq
            """
            query_params = [document_id, *params, limit]
        else:
            freq_sql = """
                (SELECT COALESCE(SUM(frequency), 0) FROM word_occurrences o
                 WHERE o.word_id = w.id) AS freq
            """
            query_params = [*params, limit]
        rows = self._all(
            f"""
            SELECT w.id,
                   {freq_sql}
            FROM words w
            JOIN learning_states s ON s.word_id = w.id
            WHERE {clause}
            ORDER BY {order}
            LIMIT ?
            """,
            tuple(query_params),
        )
        return [int(row["id"]) for row in rows]

    def create_session(self, kind: str, mode: str, document_id: int | None, deck_id: int | None, items: list[dict]) -> int:
        with self._guard():
            now = to_iso(now_local())
            cursor = self.conn.execute(
                """
                INSERT INTO study_sessions(
                    kind, mode, document_id, deck_id, status, cursor_index, started_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', 0, ?, ?)
                """,
                (kind, mode, document_id, deck_id, now, now),
            )
            session_id = int(cursor.lastrowid)
            for position, item in enumerate(items):
                self.conn.execute(
                    """
                    INSERT INTO session_items(
                        session_id, word_id, sense_id, position, prompt_pos, correct_gloss,
                        options_json, example
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        item["word_id"],
                        item.get("sense_id"),
                        position,
                        item.get("pos") or "",
                        item.get("correct") or "",
                        json.dumps(item.get("options") or [], ensure_ascii=False),
                        item.get("example"),
                    ),
                )
            return session_id

    def get_session(self, session_id: int) -> dict | None:
        return self._one("SELECT * FROM study_sessions WHERE id = ?", (session_id,))

    def get_active_session(self, kind: str) -> dict | None:
        return self._one(
            """
            SELECT * FROM study_sessions
            WHERE kind = ? AND status = 'active'
            ORDER BY id DESC LIMIT 1
            """,
            (kind,),
        )

    def session_items(self, session_id: int) -> list[dict]:
        items = self._all(
            """
            SELECT i.*, w.lemma, w.display, w.phonetic, w.phonetic_source
            FROM session_items i
            JOIN words w ON w.id = i.word_id
            WHERE i.session_id = ?
            ORDER BY i.position
            """,
            (session_id,),
        )
        for item in items:
            item["options"] = json.loads(item["options_json"] or "[]")
            item["senses"] = self.senses_of(item["word_id"])
        return items

    def save_answer(
        self,
        *,
        session_id: int,
        item_id: int,
        word_id: int,
        result: str | None,
        rating: str,
        chosen: str | None,
        correct_gloss: str,
        state_before: MemoryState,
        state_after: MemoryState,
        mode: str,
        correct_flag: int | None,
    ) -> int:
        with self._guard():
            now = now_local()
            now_text = to_iso(now)
            self.conn.execute(
                """
                UPDATE session_items
                SET answer = ?, result = ?, rating = ?, answered_at = ?
                WHERE id = ?
                """,
                (chosen, result, rating, now_text, item_id),
            )
            self.save_state(word_id, state_after)
            cursor = self.conn.execute(
                """
                INSERT INTO review_logs(
                    word_id, session_id, mode, rating, correct, chosen_gloss, correct_gloss,
                    ease_before, ease_after, interval_before, interval_after, next_review_at,
                    day, created_at, state_before_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    word_id,
                    session_id,
                    mode,
                    rating,
                    correct_flag,
                    chosen,
                    correct_gloss,
                    state_before.ease,
                    state_after.ease,
                    state_before.interval_days,
                    state_after.interval_days,
                    to_iso(state_after.next_review_at),
                    today_str(),
                    now_text,
                    json.dumps(state_to_dict(state_before), ensure_ascii=False),
                ),
            )
            log_id = int(cursor.lastrowid)
            self.conn.execute(
                "UPDATE study_sessions SET updated_at = ? WHERE id = ?",
                (now_text, session_id),
            )
            remaining = self.conn.execute(
                "SELECT COUNT(*) FROM session_items WHERE session_id = ? AND result IS NULL",
                (session_id,),
            ).fetchone()[0]
            if int(remaining) == 0:
                self.conn.execute(
                    "UPDATE study_sessions SET status = 'completed', finished_at = ?, updated_at = ? WHERE id = ?",
                    (now_text, now_text, session_id),
                )
            studied = 0 if rating == "skip" else 1
            self._bump_daily(
                studied=studied,
                new_learned=1 if mode == "learn" and rating != "skip" else 0,
                reviewed=1 if mode == "review" and rating != "skip" else 0,
                correct=1 if correct_flag == 1 else 0,
                wrong=1 if correct_flag == 0 else 0,
            )
            return log_id

    def amend_answer(self, log_id: int, word_id: int, state_after: MemoryState, rating: str, correct_flag: int | None) -> None:
        with self._guard():
            previous = self._one("SELECT * FROM review_logs WHERE id = ?", (log_id,))
            if not previous:
                return
            self.save_state(word_id, state_after)
            self.conn.execute(
                """
                UPDATE review_logs
                SET rating = ?, correct = ?, ease_after = ?, interval_after = ?, next_review_at = ?
                WHERE id = ?
                """,
                (
                    rating,
                    correct_flag,
                    state_after.ease,
                    state_after.interval_days,
                    to_iso(state_after.next_review_at),
                    log_id,
                ),
            )
            self.conn.execute("UPDATE session_items SET rating = ? WHERE session_id = ? AND word_id = ? AND answered_at = ?", (
                rating,
                previous["session_id"],
                word_id,
                previous["created_at"],
            ))
            old = previous["correct"]
            if old != correct_flag and previous["day"] == today_str():
                self._bump_daily(
                    correct=(1 if correct_flag == 1 else 0) - (1 if old == 1 else 0),
                    wrong=(1 if correct_flag == 0 else 0) - (1 if old == 0 else 0),
                )

    def replace_placement_answer(
        self,
        *,
        log_id: int,
        item_id: int,
        word_id: int,
        result: str,
        rating: str,
        state_after: MemoryState,
        correct_flag: int | None,
    ) -> None:
        with self._guard():
            previous = self._one("SELECT * FROM review_logs WHERE id = ?", (log_id,))
            if not previous:
                return
            self.save_state(word_id, state_after)
            self.conn.execute(
                """
                UPDATE review_logs
                SET rating = ?, correct = ?, ease_after = ?, interval_after = ?, next_review_at = ?
                WHERE id = ?
                """,
                (
                    rating,
                    correct_flag,
                    state_after.ease,
                    state_after.interval_days,
                    to_iso(state_after.next_review_at),
                    log_id,
                ),
            )
            self.conn.execute(
                "UPDATE session_items SET result = ?, rating = ? WHERE id = ?",
                (result, rating, item_id),
            )
            old = previous["correct"]
            correct_delta = 0
            wrong_delta = 0
            if previous["day"] == today_str() and old != correct_flag:
                correct_delta = (1 if correct_flag == 1 else 0) - (1 if old == 1 else 0)
                wrong_delta = (1 if correct_flag == 0 else 0) - (1 if old == 0 else 0)
            self._bump_daily(correct=correct_delta, wrong=wrong_delta)

    def abandon_session(self, session_id: int) -> None:
        with self._guard():
            self.conn.execute(
                "UPDATE study_sessions SET status = 'abandoned', updated_at = ? WHERE id = ? AND status = 'active'",
                (to_iso(now_local()), session_id),
            )

    def recent_sessions(self, kind: str, limit: int = 12) -> list[dict]:
        return self._all(
            """
            SELECT * FROM study_sessions
            WHERE kind = ? AND status = 'completed'
            ORDER BY finished_at DESC LIMIT ?
            """,
            (kind, limit),
        )

    def undo_last_review(self) -> dict | None:
        row = self._one(
            """
            SELECT r.*, w.lemma
            FROM review_logs r
            JOIN words w ON w.id = r.word_id
            WHERE COALESCE(r.undone, 0) = 0 AND r.state_before_json IS NOT NULL
            ORDER BY r.id DESC
            LIMIT 1
            """
        )
        if not row:
            return None
        before = state_from_dict(json.loads(row["state_before_json"]))
        with self._guard():
            self.save_state(int(row["word_id"]), before)
            self.conn.execute("UPDATE review_logs SET undone = 1 WHERE id = ?", (row["id"],))
            if row["session_id"]:
                self.conn.execute(
                    """
                    UPDATE session_items
                    SET answer = NULL, result = NULL, rating = NULL, answered_at = NULL
                    WHERE session_id = ? AND word_id = ? AND answered_at = ?
                    """,
                    (row["session_id"], row["word_id"], row["created_at"]),
                )
                self.conn.execute(
                    """
                    UPDATE study_sessions
                    SET status = 'active', finished_at = NULL, updated_at = ?
                    WHERE id = ? AND status = 'completed'
                    """,
                    (to_iso(now_local()), row["session_id"]),
                )
            if row["day"] == today_str():
                rating = row["rating"] or ""
                correct_flag = row["correct"]
                self._bump_daily(
                    studied=0 if rating == "skip" else -1,
                    new_learned=-1 if row["mode"] == "learn" and rating != "skip" else 0,
                    reviewed=-1 if row["mode"] == "review" and rating != "skip" else 0,
                    correct=-1 if correct_flag == 1 else 0,
                    wrong=-1 if correct_flag == 0 else 0,
                )
        return {"word_id": int(row["word_id"]), "lemma": row["lemma"], "log_id": int(row["id"])}

    def due_forecast(self, days: int = 7) -> list[dict]:
        from datetime import timedelta

        start = now_local().date()
        labels = [(start + timedelta(days=offset)).isoformat() for offset in range(max(1, days))]
        rows = self._all(
            """
            SELECT next_review_at FROM learning_states
            WHERE next_review_at IS NOT NULL AND substr(next_review_at, 1, 10) <= ?
            """,
            (labels[-1],),
        )
        buckets = {label: 0 for label in labels}
        today = labels[0]
        for row in rows:
            day = (row["next_review_at"] or "")[:10]
            if day <= today:
                buckets[today] += 1
            elif day in buckets:
                buckets[day] += 1
        return [{"day": label[5:], "count": buckets[label]} for label in labels]

    def leech_count(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM learning_states WHERE leech = 1")
        return int(row["n"] if row else 0)

    def _bump_daily(self, *, studied=0, new_learned=0, reviewed=0, correct=0, wrong=0) -> None:
        day = today_str()
        self.conn.execute("INSERT INTO daily_stats(day) VALUES (?) ON CONFLICT(day) DO NOTHING", (day,))
        self.conn.execute(
            """
            UPDATE daily_stats SET
                studied = MAX(0, studied + ?),
                new_learned = MAX(0, new_learned + ?),
                reviewed = MAX(0, reviewed + ?),
                correct = MAX(0, correct + ?),
                wrong = MAX(0, wrong + ?),
                mastered_total = (SELECT COUNT(*) FROM learning_states WHERE status = 'mastered'),
                learning_total = (SELECT COUNT(*) FROM learning_states WHERE status IN ('learning', 'reviewing')),
                untested_total = (SELECT COUNT(*) FROM learning_states WHERE status = 'untested')
            WHERE day = ?
            """,
            (studied, new_learned, reviewed, correct, wrong, day),
        )

    def status_counts(self) -> dict[str, int]:
        rows = self._all("SELECT status, COUNT(*) AS n FROM learning_states GROUP BY status")
        counts = {row["status"]: int(row["n"]) for row in rows}
        for key in ("untested", "pending", "learning", "reviewing", "mastered"):
            counts.setdefault(key, 0)
        counts["total"] = sum(counts[key] for key in ("untested", "pending", "learning", "reviewing", "mastered"))
        return counts

    def average_mastery(self) -> float:
        row = self.conn.execute("SELECT AVG(mastery) FROM learning_states").fetchone()
        return float(row[0] or 0)

    def dashboard(self, daily_goal: int) -> dict:
        now = to_iso(now_local())
        today = today_str()
        due = self._one(
            """
            SELECT
                SUM(CASE WHEN status != 'mastered' THEN 1 ELSE 0 END) AS learning,
                SUM(CASE WHEN status = 'mastered' THEN 1 ELSE 0 END) AS mastered
            FROM learning_states
            WHERE next_review_at IS NOT NULL AND next_review_at <= ?
            """,
            (now,),
        ) or {"learning": 0, "mastered": 0}
        studied = self._one(
            "SELECT COUNT(DISTINCT word_id) AS n FROM review_logs WHERE day = ? AND rating != 'skip'",
            (today,),
        )
        new_learned = self._one(
            "SELECT COUNT(DISTINCT word_id) AS n FROM review_logs WHERE day = ? AND mode = 'learn'",
            (today,),
        )
        counts = self.status_counts()
        return {
            "due_learning": int(due["learning"] or 0),
            "due_mastered": int(due["mastered"] or 0),
            "due_total": int(due["learning"] or 0) + int(due["mastered"] or 0),
            "daily_goal": daily_goal,
            "studied_today": int(studied["n"] if studied else 0),
            "new_today": int(new_learned["n"] if new_learned else 0),
            "counts": counts,
            "average_mastery": round(self.average_mastery(), 1),
            "streak": self.streak(),
        }

    def activity_days(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT day FROM review_logs WHERE rating != 'skip' ORDER BY day"
        ).fetchall()
        return [row[0] for row in rows]

    def streak(self) -> int:
        from datetime import timedelta

        days = set(self.activity_days())
        cursor = now_local().date()
        if cursor.isoformat() not in days:
            cursor = cursor - timedelta(days=1)
        streak = 0
        while cursor.isoformat() in days:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    def daily_series(self, days: int) -> list[dict]:
        from datetime import timedelta

        today = now_local().date()
        start = today - timedelta(days=days - 1)
        rows = {
            row["day"]: row
            for row in self._all("SELECT * FROM daily_stats WHERE day >= ?", (start.isoformat(),))
        }
        series = []
        for offset in range(days):
            day = (start + timedelta(days=offset)).isoformat()
            row = rows.get(day)
            series.append(
                {
                    "day": day[5:],
                    "studied": int(row["studied"]) if row else 0,
                    "correct": int(row["correct"]) if row else 0,
                    "wrong": int(row["wrong"]) if row else 0,
                    "mastered_total": int(row["mastered_total"]) if row else 0,
                }
            )
        return series

    def top_wrong(self, limit: int = 8, document_id: int | None = None) -> list[dict]:
        clause = "s.wrong_count > 0"
        params: list = []
        if document_id:
            clause += " AND w.id IN (SELECT word_id FROM word_occurrences WHERE document_id = ?)"
            params.append(document_id)
        params.append(limit)
        return self._all(
            f"""
            SELECT w.lemma, s.wrong_count, s.mastery, s.status,
                   (SELECT gloss_zh FROM senses se WHERE se.word_id = w.id
                    ORDER BY se.is_primary DESC, se.sort_order LIMIT 1) AS gloss
            FROM learning_states s
            JOIN words w ON w.id = s.word_id
            WHERE {clause}
            ORDER BY s.wrong_count DESC, w.lemma
            LIMIT ?
            """,
            tuple(params),
        )

    def placement_trend(self, limit: int = 12) -> list[dict]:
        sessions = self.recent_sessions("placement", limit)
        trend = []
        for session in reversed(sessions):
            counts = self.session_result_counts(session["id"])
            graded = counts.get("correct", 0) + counts.get("wrong", 0) + counts.get("unknown", 0)
            accuracy = (counts.get("correct", 0) / graded * 100) if graded else 0
            trend.append({"label": (session["finished_at"] or "")[5:10], "accuracy": round(accuracy, 1)})
        return trend

    def session_result_counts(self, session_id: int) -> dict[str, int]:
        rows = self._all(
            """
            SELECT result, COUNT(*) AS n
            FROM session_items
            WHERE session_id = ? AND result IS NOT NULL
            GROUP BY result
            """,
            (session_id,),
        )
        return {row["result"]: int(row["n"]) for row in rows}

    def export_rows(self, *, deck_id: int | None = None, statuses: tuple[str, ...] | None = None) -> list[dict]:
        where = ["1 = 1"]
        params: list = []
        if deck_id:
            where.append("w.id IN (SELECT word_id FROM deck_words WHERE deck_id = ?)")
            params.append(deck_id)
        if statuses:
            where.append("s.status IN (" + ",".join("?" for _ in statuses) + ")")
            params.extend(statuses)
        return self._all(
            f"""
            SELECT w.lemma, w.display, w.phonetic, s.status, s.mastery, s.wrong_count,
                   s.next_review_at, IFNULL(s.notes, '') AS notes,
                   se.pos, se.gloss_zh, IFNULL(se.gloss_en, '') AS gloss_en,
                   (SELECT COALESCE(SUM(frequency), 0) FROM word_occurrences o WHERE o.word_id = w.id) AS frequency
            FROM words w
            JOIN learning_states s ON s.word_id = w.id
            LEFT JOIN senses se ON se.word_id = w.id
            WHERE {' AND '.join(where)}
            ORDER BY w.lemma, se.sort_order, se.id
            """,
            params,
        )

    def active_file_documents(self) -> list[dict]:
        return self._all("SELECT * FROM documents WHERE kind = 'file' AND status != 'missing'")
