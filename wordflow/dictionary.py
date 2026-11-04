"""ECDICT 本地词典。没有可靠释义时返回空，调用方必须标记为待补充。"""

from __future__ import annotations

import random
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from wordflow.gloss import has_cjk, segments
from wordflow.lemma import heuristic_lemma

_POS_LINE = re.compile(r"^([A-Za-z./]+)\.?\s+(.+)$")
_POS_MAP = {
    "n": "n",
    "noun": "n",
    "pl": "n",
    "v": "v",
    "vt": "v",
    "vi": "v",
    "verb": "v",
    "aux": "v",
    "modal": "v",
    "link": "v",
    "a": "adj",
    "adj": "adj",
    "j": "adj",
    "ad": "adv",
    "adv": "adv",
    "r": "adv",
    "prep": "prep",
    "conj": "conj",
    "pron": "pron",
    "art": "art",
    "num": "num",
    "int": "int",
}


@dataclass
class DictSense:
    pos: str
    gloss_zh: str
    gloss_en: str = ""


@dataclass
class DictEntry:
    word: str
    phonetic: str | None
    senses: list[DictSense] = field(default_factory=list)
    lemma: str = ""
    frq: int = 0
    bnc: int = 0
    oxford: int = 0
    collins: int = 0

    def __post_init__(self) -> None:
        if not self.lemma:
            self.lemma = self.word


class Dictionary:
    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        self.available = False
        self.error = ""
        self.entry_count = 0
        self.max_id = 0
        self.conn: sqlite3.Connection | None = None
        self.table = ""
        self.id_col = "id"
        self._cache: dict[str, DictEntry | None] = {}
        self._lemma_cache: dict[str, str] = {}
        if self.path is None or not self.path.is_file():
            self.error = "未找到本地词典文件"
            return
        try:
            self.conn = sqlite3.connect(str(self.path))
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA query_only = ON")
            self._detect()
            self.available = True
        except Exception as exc:
            self.error = f"词典无法打开：{exc}"
            self.close()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def lookup(self, word: str) -> DictEntry | None:
        key = _normalize(word)
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]
        entry = self._query(key)
        if len(self._cache) > 50000:
            self._cache.clear()
        self._cache[key] = entry
        return entry

    def has_entry(self, word: str) -> bool:
        return self.lookup(word) is not None

    def is_common(self, word: str) -> bool:
        entry = self.lookup(word)
        if entry is None:
            return False
        if 0 < entry.frq <= 40000:
            return True
        if 0 < entry.bnc <= 30000:
            return True
        return entry.oxford == 1 or entry.collins >= 1

    def resolve_lemma(self, token: str) -> str:
        word = _normalize(token)
        if not word:
            return ""
        cached = self._lemma_cache.get(word)
        if cached:
            return cached
        entry = self.lookup(word)
        if entry is not None:
            lemma = entry.lemma or word
        else:
            lemma = heuristic_lemma(word, self.has_entry)
        self._lemma_cache[word] = lemma
        return lemma

    def sample_rows(self, batch: int = 40) -> list[sqlite3.Row]:
        if not self.available or self.conn is None or self.max_id <= 0:
            return []
        start = random.randint(1, self.max_id)
        sql = (
            f"SELECT word, translation, pos FROM {self.table} "
            f"WHERE {self.id_col} >= ? AND translation IS NOT NULL AND translation != '' LIMIT ?"
        )
        rows = list(self.conn.execute(sql, (start, batch)))
        if len(rows) < max(8, batch // 3):
            extra = (
                f"SELECT word, translation, pos FROM {self.table} "
                f"WHERE {self.id_col} < ? AND translation IS NOT NULL AND translation != '' LIMIT ?"
            )
            rows.extend(self.conn.execute(extra, (start, batch)))
        return rows

    def _detect(self) -> None:
        assert self.conn is not None
        tables = [
            row[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        if "stardict" in tables:
            self.table = "stardict"
        elif "ecdict" in tables:
            self.table = "ecdict"
        else:
            raise RuntimeError("词典中没有 stardict 或 ecdict 表")
        columns = {row[1] for row in self.conn.execute(f"PRAGMA table_info({self.table})")}
        required = {"word", "translation"}
        if not required <= columns:
            raise RuntimeError("词典缺少 word 或 translation 字段")
        self.id_col = "id" if "id" in columns else "rowid"
        count, maximum = self.conn.execute(
            f"SELECT COUNT(*), MAX({self.id_col}) FROM {self.table}"
        ).fetchone()
        self.entry_count = int(count or 0)
        self.max_id = int(maximum or 0)

    def _query(self, word: str) -> DictEntry | None:
        if not self.available or self.conn is None:
            return None
        row = self.conn.execute(
            f"SELECT * FROM {self.table} WHERE word = ? COLLATE NOCASE LIMIT 1",
            (word,),
        ).fetchone()
        if row is None:
            return None
        data = {key.lower(): row[key] for key in row.keys()}
        exchange = _parse_exchange(str(data.get("exchange") or ""))
        phonetic = _clean_phonetic(data.get("phonetic"))
        definition = str(data.get("definition") or "").strip()
        senses = _parse_translation(str(data.get("translation") or ""), definition)
        parent = exchange.get("0", "").strip().lower()
        # 自带中文释义的词保持独立身份。ECDICT 会把 meaning 标成 mean 的派生形，
        # 合并后会学到另一个词。没有可用释义的屈折行（如 running）才跟随原型。
        lemma = word if senses or not parent else parent
        return DictEntry(
            word=str(data.get("word") or word).lower(),
            phonetic=phonetic,
            senses=senses,
            lemma=lemma.lower(),
            frq=_as_int(data.get("frq")),
            bnc=_as_int(data.get("bnc")),
            oxford=_as_int(data.get("oxford")),
            collins=_as_int(data.get("collins")),
        )


def normalize_pos(pos: str) -> str:
    raw = (pos or "").strip().lower().rstrip(".")
    if not raw:
        return ""
    if "/" in raw and ":" in raw:
        best_name = ""
        best_score = -1
        for part in raw.split("/"):
            name, _, score = part.partition(":")
            try:
                value = int(score) if score else 0
            except ValueError:
                value = 0
            if value >= best_score:
                best_score = value
                best_name = name
        raw = best_name or raw
    raw = raw.split(":")[0].split("/")[0].strip(".")
    return _POS_MAP.get(raw, raw[:8])


def _parse_exchange(exchange: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in exchange.split("/"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        if key and value and key not in found:
            found[key] = value
    return found


def _parse_translation(translation: str, definition: str) -> list[DictSense]:
    if not translation:
        return []
    senses: list[DictSense] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in translation.replace("\\n", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        matched = _POS_LINE.match(line)
        if matched and len(matched.group(1)) <= 12:
            pos = normalize_pos(matched.group(1))
            body = matched.group(2).strip()
        else:
            pos = ""
            body = line
        if not has_cjk(body) or not segments(body):
            continue
        key = (pos, body)
        if key in seen:
            continue
        seen.add(key)
        senses.append(DictSense(pos=pos, gloss_zh=body))
    if senses and definition:
        senses[0].gloss_en = definition[:500]
    return senses


def _clean_phonetic(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("/")
    if not text or text in {"-", "--", "null"}:
        return None
    return text


def _normalize(word: str) -> str:
    return word.strip().lower().replace("\u2019", "'").replace("\u2018", "'")


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
