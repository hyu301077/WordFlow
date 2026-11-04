"""手动添加、状态移动，以及 CSV / JSON 词表交换。"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from wordflow.srs import apply_manual_status
from wordflow.timeutil import now_local

_WORD = re.compile(r"^[A-Za-z][A-Za-z'-]+$")
_FIELDS = [
    "lemma",
    "display",
    "phonetic",
    "pos",
    "gloss_zh",
    "gloss_en",
    "status",
    "mastery",
    "frequency",
    "wrong_count",
    "next_review_at",
    "notes",
]


def add_manual_word(
    store,
    dictionary,
    *,
    text: str,
    phonetic: str = "",
    pos: str = "",
    gloss_zh: str = "",
    gloss_en: str = "",
    notes: str = "",
    status: str = "learning",
    keep_dictionary_senses: bool = False,
) -> tuple[int, bool]:
    raw = text.strip().lower().replace("\u2019", "'")
    if not _WORD.match(raw):
        raise ValueError("请输入由英文字母组成的单词")
    lemma = dictionary.resolve_lemma(raw) if dictionary and dictionary.available else raw
    entry = dictionary.lookup(lemma) if dictionary else None
    if entry is None and dictionary and dictionary.available:
        entry = dictionary.lookup(raw)
        if entry is not None:
            lemma = entry.lemma or raw
    existing = store.get_word_by_lemma(lemma)
    word_id = store.ensure_word(lemma, raw if raw == lemma else lemma, entry)
    if phonetic.strip():
        same = bool(entry and entry.phonetic and phonetic.strip() == entry.phonetic)
        store.update_phonetic(word_id, phonetic.strip(), "dictionary" if same else "manual")
    if gloss_zh.strip() and not keep_dictionary_senses:
        store.replace_senses(
            word_id,
            [
                {
                    "pos": pos.strip(),
                    "gloss_zh": gloss_zh.strip(),
                    "gloss_en": gloss_en.strip(),
                    "is_primary": True,
                }
            ],
        )
    state = store.load_state(word_id)
    state.notes = notes.strip()
    if existing is None or state.status in {"untested", "pending"} or not keep_dictionary_senses:
        state = apply_manual_status(state, status, now_local())
        state.notes = notes.strip()
    store.save_state(word_id, state)
    return word_id, existing is None


def batch_add(store, dictionary, text: str, status: str = "learning") -> dict:
    tokens: list[str] = []
    invalid = 0
    for line in text.splitlines():
        for piece in re.split(r"[,;，；\s]+", line.strip()):
            if not piece:
                continue
            if _WORD.match(piece):
                tokens.append(piece)
            else:
                invalid += 1
    added = 0
    existed = 0
    pending = 0
    for token in tokens:
        lemma = dictionary.resolve_lemma(token) if dictionary and dictionary.available else token.lower()
        entry = dictionary.lookup(lemma) if dictionary else None
        if entry is None and dictionary:
            entry = dictionary.lookup(token)
            if entry is not None:
                lemma = entry.lemma or token.lower()
        existing = store.get_word_by_lemma(lemma)
        store.ensure_word(lemma, lemma, entry)
        word = store.get_word_by_lemma(lemma)
        assert word is not None
        if not entry or not entry.senses:
            pending += 1
        if existing is None:
            state = apply_manual_status(store.load_state(word["id"]), status, now_local())
            store.save_state(word["id"], state)
            added += 1
        else:
            state = store.load_state(word["id"])
            if state.status in {"untested", "pending"}:
                state = apply_manual_status(state, status, now_local())
                store.save_state(word["id"], state)
                added += 1
            else:
                existed += 1
    return {"added": added, "existed": existed, "pending": pending, "invalid": invalid}


def move_words(store, word_ids: list[int], status: str) -> None:
    now = now_local()
    for word_id in word_ids:
        state = apply_manual_status(store.load_state(word_id), status, now)
        store.save_state(word_id, state)


def save_word_edit(store, word_id: int, *, display: str, phonetic: str, senses: list[dict], notes: str, status: str, deck_ids: list[int], example: str = "") -> None:
    current = store.get_word(word_id)
    store.update_display(word_id, display.strip() or current["lemma"])
    if phonetic.strip() != (current["phonetic"] or ""):
        if phonetic.strip():
            store.update_phonetic(word_id, phonetic.strip(), "manual")
        else:
            store.update_phonetic(word_id, None, "missing")
    store.replace_senses(word_id, senses)
    if example.strip():
        store.add_example(word_id, None, example.strip(), source="user")
    state = store.load_state(word_id)
    if status and status != state.status:
        state = apply_manual_status(state, status, now_local())
    state.notes = notes.strip()
    store.save_state(word_id, state)
    if deck_ids:
        store.set_word_decks(word_id, deck_ids)


def export_csv(path: Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in _FIELDS})


def export_json(path: Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{key: row.get(key, "") for key in _FIELDS} for row in rows]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def import_table(store, dictionary, path: Path) -> dict:
    path = Path(path)
    rows = _read_table(path)
    grouped: dict[str, list[dict]] = {}
    invalid = 0
    for row in rows:
        lemma = str(row.get("lemma") or row.get("word") or "").strip().lower()
        if not _WORD.match(lemma):
            invalid += 1
            continue
        grouped.setdefault(lemma, []).append(row)
    added = 0
    updated = 0
    for lemma, items in grouped.items():
        existing = store.get_word_by_lemma(lemma)
        entry = dictionary.lookup(lemma) if dictionary else None
        word_id = store.ensure_word(lemma, str(items[0].get("display") or lemma), entry)
        phonetic = str(items[0].get("phonetic") or "").strip()
        if phonetic:
            store.update_phonetic(word_id, phonetic, "manual")
        senses = []
        for index, item in enumerate(items):
            gloss = str(item.get("gloss_zh") or "").strip()
            if not gloss:
                continue
            senses.append(
                {
                    "pos": str(item.get("pos") or "").strip(),
                    "gloss_zh": gloss,
                    "gloss_en": str(item.get("gloss_en") or "").strip(),
                    "is_primary": index == 0,
                }
            )
        if senses:
            store.replace_senses(word_id, senses)
        notes = str(items[0].get("notes") or "")
        status = str(items[0].get("status") or "").strip()
        state = store.load_state(word_id)
        if status in {"untested", "pending", "learning", "reviewing", "mastered"}:
            state = apply_manual_status(state, status, now_local())
        elif existing is None:
            state = apply_manual_status(state, "learning", now_local())
        state.notes = notes or state.notes
        store.save_state(word_id, state)
        if existing is None:
            added += 1
        else:
            updated += 1
    return {"added": added, "updated": updated, "invalid": invalid}


def _read_table(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("words", [])
        return list(data)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
