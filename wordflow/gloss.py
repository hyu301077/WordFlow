"""中文释义的切分与比对。只处理已有文本，不生成新义项。"""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]")
_PAREN = re.compile(r"[（(][^）)]*[）)]")
_BRACKET = re.compile(r"\[[^\]]*\]")
_SPLIT = re.compile(r"[；;，,、|/]+")


def has_cjk(text: str | None) -> bool:
    return bool(text and _CJK.search(text))


def clean_gloss(text: str | None) -> str:
    if not text:
        return ""
    value = _BRACKET.sub("", text)
    value = _PAREN.sub("", value)
    value = re.sub(r"\s+", "", value)
    return value.strip(" .。;；,，、")


def segments(text: str | None) -> list[str]:
    cleaned = clean_gloss(text)
    if not cleaned:
        return []
    parts: list[str] = []
    for piece in _SPLIT.split(cleaned):
        piece = piece.strip(" .。;；,，、")
        if len(piece) >= 2 and has_cjk(piece):
            parts.append(piece[:18])
    return parts


def short_gloss(text: str | None) -> str | None:
    parts = segments(text)
    if not parts:
        return None
    if len(parts) == 1 or len(parts[0]) >= 4:
        return parts[0]
    return "；".join(parts[:2])[:18]


def norm_gloss(text: str | None) -> str:
    return clean_gloss(text).lower()


def forbidden_norms(glosses: list[str]) -> set[str]:
    found: set[str] = set()
    for gloss in glosses:
        if not gloss:
            continue
        found.add(norm_gloss(gloss))
        for part in segments(gloss):
            found.add(norm_gloss(part))
        found.discard("")
    return found


def conflicts(candidate: str, forbidden: set[str]) -> bool:
    parts = segments(candidate) or ([clean_gloss(candidate)] if clean_gloss(candidate) else [])
    norms = {norm_gloss(part) for part in parts if part}
    if any(item in forbidden for item in norms):
        return True
    for item in norms:
        if len(item) < 2:
            continue
        for blocked in forbidden:
            if len(blocked) < 2:
                continue
            if item in blocked or blocked in item:
                return True
    return False
