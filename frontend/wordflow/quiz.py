"""四选一题目。正确项和干扰项都来自已有释义，凑不齐四个互不冲突的选项就不出题。"""

from __future__ import annotations

import random
from dataclasses import dataclass

from wordflow.context_pos import guess_pos, pos_matches
from wordflow.dictionary import _parse_translation, normalize_pos
from wordflow.gloss import conflicts, forbidden_norms, norm_gloss, short_gloss


@dataclass
class Question:
    word_id: int
    sense_id: int | None
    pos: str
    correct: str
    options: list[str]
    example: str | None


class QuizBuilder:
    def __init__(self, dictionary):
        self.dictionary = dictionary

    def build(
        self,
        *,
        word_id: int,
        senses: list[dict],
        example: str | None,
        forms: list[str] | None = None,
    ) -> Question | None:
        usable = []
        for sense in senses:
            gloss = short_gloss(sense.get("gloss_zh"))
            if gloss:
                usable.append((sense, gloss))
        if not usable:
            return None
        primary_sense, correct = _sense_for_sentence(usable, example, forms or [])
        blocked = forbidden_norms([sense.get("gloss_zh") or "" for sense in senses])
        blocked.add(norm_gloss(correct))
        distractors = self._distractors(primary_sense.get("pos") or "", blocked, correct)
        if len(distractors) < 3:
            return None
        options = distractors[:3] + [correct]
        random.shuffle(options)
        normalized = [norm_gloss(option) for option in options]
        if len(set(normalized)) != 4 or normalized.count(norm_gloss(correct)) != 1:
            return None
        return Question(
            word_id=word_id,
            sense_id=primary_sense.get("id"),
            pos=primary_sense.get("pos") or "",
            correct=correct,
            options=options,
            example=example,
        )

    def _distractors(self, pos: str, blocked: set[str], correct: str) -> list[str]:
        if not self.dictionary.available:
            return []
        found: list[str] = []
        seen: set[str] = set()
        for strict in (True, False):
            for _ in range(8):
                if len(found) >= 3:
                    return found
                for row in self.dictionary.sample_rows(60):
                    for sense in _parse_translation(row["translation"] or "", ""):
                        if strict and normalize_pos(pos) != normalize_pos(sense.pos):
                            continue
                        gloss = short_gloss(sense.gloss_zh)
                        if not gloss:
                            continue
                        key = norm_gloss(gloss)
                        if key in seen or conflicts(gloss, blocked):
                            continue
                        if strict and abs(len(gloss) - len(correct)) > max(8, len(correct)):
                            continue
                        found.append(gloss)
                        seen.add(key)
                        blocked = set(blocked)
                        blocked.update(forbidden_norms([gloss]))
                        if len(found) >= 3:
                            return found
        return found


def _sense_for_sentence(usable: list[tuple[dict, str]], example: str | None, forms: list[str]) -> tuple[dict, str]:
    primary = next(((sense, gloss) for sense, gloss in usable if sense.get("is_primary")), usable[0])
    if not example or not forms:
        return primary
    guessed = guess_pos(example, forms)
    if not guessed:
        return primary
    for sense, gloss in usable:
        if pos_matches(sense.get("pos") or "", guessed):
            return sense, gloss
    return primary
