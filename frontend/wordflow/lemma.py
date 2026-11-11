"""保守词形归一。

词典里已经标明的原形优先。词不在词典中时，只有一个候选原形能在词典里找到，才合并。
多个候选或没有候选时保持原词，避免把不相干的词并到一起。
"""

from __future__ import annotations

_VOWELS = set("aeiou")

IRREGULAR = {
    "was": "be",
    "were": "be",
    "been": "be",
    "am": "be",
    "is": "be",
    "are": "be",
    "did": "do",
    "done": "do",
    "does": "do",
    "has": "have",
    "had": "have",
    "went": "go",
    "gone": "go",
    "ran": "run",
    "children": "child",
    "men": "man",
    "women": "woman",
    "mice": "mouse",
    "feet": "foot",
    "teeth": "tooth",
    "geese": "goose",
}

_BAN = {
    "the",
    "and",
    "for",
    "you",
    "are",
    "was",
    "has",
    "her",
    "his",
    "its",
    "not",
    "but",
    "had",
    "did",
    "can",
    "may",
    "she",
    "him",
    "our",
    "out",
    "all",
    "any",
    "one",
    "who",
    "how",
    "its",
}


def heuristic_lemma(word: str, has_entry) -> str:
    if word in IRREGULAR and has_entry(IRREGULAR[word]):
        return IRREGULAR[word]
    candidates: list[str] = []
    if word.endswith("ies") and len(word) > 4:
        candidates.append(word[:-3] + "y")
    if word.endswith("ves") and len(word) > 4:
        stem = word[:-3]
        candidates.append(stem + "f")
        candidates.append(stem + "fe")
    if word.endswith("ing") and len(word) >= 5:
        stem = word[:-3]
        candidates.extend(_stem_variants(stem))
    if word.endswith("ed") and len(word) >= 4:
        stem = word[:-2]
        candidates.extend(_stem_variants(stem))
        if stem.endswith("i") and len(stem) >= 2:
            candidates.append(stem[:-1] + "y")
    if word.endswith("es") and len(word) > 4:
        candidates.append(word[:-2])
        candidates.append(word[:-1])
    elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        candidates.append(word[:-1])

    found: list[str] = []
    for candidate in candidates:
        if candidate == word or len(candidate) < 3 or candidate in _BAN:
            continue
        if candidate not in found and has_entry(candidate):
            found.append(candidate)
    if len(found) == 1:
        return found[0]
    return word


def _stem_variants(stem: str) -> list[str]:
    variants = []
    if len(stem) >= 2:
        variants.append(stem)
        variants.append(stem + "e")
    if (
        len(stem) >= 3
        and stem[-1] == stem[-2]
        and stem[-1] not in _VOWELS
    ):
        variants.append(stem[:-1])
        variants.append(stem[:-1] + "e")
    return variants
