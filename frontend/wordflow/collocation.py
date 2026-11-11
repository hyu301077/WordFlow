"""从用户自己的例句里抽出相邻搭配。不编造词书里的短语。"""

from __future__ import annotations

import re
from collections import Counter

_TOKEN = re.compile(r"[A-Za-z][A-Za-z'-]+")
_SKIP = {
    "a",
    "an",
    "the",
    "his",
    "her",
    "their",
    "its",
    "my",
    "your",
    "our",
    "this",
    "that",
    "these",
    "those",
    "to",
    "of",
    "in",
    "on",
    "for",
    "and",
    "or",
    "at",
    "by",
    "with",
}


def phrases_in_sentences(lemma: str, sentences: list[str], limit: int = 4) -> list[str]:
    target = (lemma or "").strip().lower()
    if not target:
        return []
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for sentence in sentences:
        tokens = _TOKEN.findall(sentence or "")
        lower = [token.lower() for token in tokens]
        for index, token in enumerate(lower):
            if token != target:
                continue
            for direction in (-1, 1):
                span = _span(tokens, lower, index, direction)
                if span is None:
                    continue
                start, end = span
                phrase = " ".join(tokens[start:end])
                key = phrase.lower()
                counts[key] += 1
                display.setdefault(key, phrase)
    ranked = sorted(counts, key=lambda key: (-counts[key], key))
    lines = []
    for key in ranked[:limit]:
        text = display[key]
        if counts[key] > 1:
            text = f"{text} ×{counts[key]}"
        lines.append(text)
    return lines


def blank_sentence(sentence: str, forms: list[str]) -> str | None:
    """把句中第一次出现的目标词换成空格。找不到就不编造句子。"""
    if not sentence:
        return None
    ordered = sorted({form.strip() for form in forms if form and form.strip()}, key=len, reverse=True)
    for form in ordered:
        pattern = re.compile(rf"\b{re.escape(form)}\b", re.IGNORECASE)
        if pattern.search(sentence):
            return pattern.sub("______", sentence, count=1)
    return None


def _span(tokens: list[str], lower: list[str], index: int, direction: int) -> tuple[int, int] | None:
    cursor = index + direction
    skipped = 0
    while 0 <= cursor < len(tokens):
        if lower[cursor] in _SKIP:
            skipped += 1
            if skipped > 1:
                return None
            cursor += direction
            continue
        if len(tokens[cursor]) < 3:
            return None
        start, end = sorted((index, cursor))
        return start, end + 1
    return None
