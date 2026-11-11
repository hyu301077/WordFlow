"""根据例句里这个词前后的词，判断它在这句中的词性。只在已有词典义项里选择。"""

from __future__ import annotations

import re

from wordflow.dictionary import normalize_pos

_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_DET = frozenset(
    "a an the this that these those my your his her its our their some any no every each another both".split()
)
_BE = frozenset("am is are was were be been being".split())
_LINK = frozenset(
    "feel feels felt seem seems seemed look looks looked become became get gets got stay stays stayed sound sounds sounded remain remains remained keep keeps kept".split()
)
_MODAL = frozenset("will would can could may might must shall should do does did".split())
_POS_ALIAS = {"interj": "int", "i": "int"}


def guess_pos(sentence: str, forms: list[str]) -> str | None:
    tokens = _TOKEN.findall(sentence or "")
    if not tokens:
        return None
    wanted = {form.strip().lower() for form in forms if form and form.strip()}
    if not wanted:
        return None
    lowered = [token.lower() for token in tokens]
    index = next((i for i, token in enumerate(lowered) if token in wanted), None)
    if index is None:
        return None
    previous = lowered[index - 1] if index else ""
    following = lowered[index + 1] if index + 1 < len(lowered) else ""
    if index == 0 and re.match(rf"^\s*{re.escape(tokens[0])}\s*,", sentence or "", re.IGNORECASE):
        return "interj"
    if previous in _DET or previous.endswith("'s"):
        return "n"
    if previous == "as":
        return "adv"
    if previous in _MODAL or previous == "to":
        return "v"
    if previous in _BE or previous in _LINK:
        return "adj"
    if _verbish(previous) and following not in _DET:
        return "adv"
    if following in {"enough", "known", "done"} or following.endswith("ly"):
        return "adv"
    return None


def pos_matches(left: str, right: str) -> bool:
    return _family(left) == _family(right) and _family(left) != ""


def _family(pos: str) -> str:
    normalized = normalize_pos(pos)
    return _POS_ALIAS.get(normalized, normalized)


def _verbish(token: str) -> bool:
    if not token or token in _DET:
        return False
    if token in _BE or token in _MODAL or token in _LINK:
        return True
    if len(token) > 4 and token.endswith("ing") and token not in {"thing", "nothing", "something", "everything"}:
        return True
    return len(token) > 3 and token.endswith("ed")
