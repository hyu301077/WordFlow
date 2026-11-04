"""摸底、学习和复习会话。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from wordflow.collocation import blank_sentence
from wordflow.constants import (
    RATING_AGAIN,
    RATING_EASY,
    RATING_GOOD,
    RATING_HARD,
    RATING_MASTERED,
)
from wordflow.gloss import short_gloss
from wordflow.quiz import Question, QuizBuilder
from wordflow.srs import apply_placement, apply_rating
from wordflow.timeutil import now_local

_PLACEMENT_RATING = {
    "correct": RATING_GOOD,
    "wrong": RATING_AGAIN,
    "unknown": RATING_AGAIN,
    "skip": "skip",
    "mastered": RATING_MASTERED,
}


class StudyService:
    def __init__(self, store, dictionary):
        self.store = store
        self.dictionary = dictionary
        self.quiz = QuizBuilder(dictionary)

    def start_placement(self, *, limit: int, document_id: int | None, deck_id: int | None, include_pending: bool) -> dict:
        ids = self.store.pick_word_ids(
            purpose="untested",
            limit=max(limit * 4, limit),
            document_id=document_id,
            deck_id=deck_id,
            include_pending=include_pending,
        )
        return self._open("placement", "quiz", ids, limit, document_id, deck_id, require_question=True)

    def start_learn(
        self,
        *,
        mode: str,
        limit: int,
        document_id: int | None,
        deck_id: int | None,
        word_ids: list[int] | None = None,
    ) -> dict:
        ids = self.store.pick_word_ids(
            purpose="new",
            limit=max(limit * 3, limit),
            document_id=document_id,
            deck_id=deck_id,
            word_ids=word_ids,
        )
        return self._open("learn", mode, ids, limit, document_id, deck_id, require_question=mode != "card")

    def start_review(
        self,
        *,
        mode: str,
        limit: int,
        deck_id: int | None,
        mistakes_only: bool = False,
        word_ids: list[int] | None = None,
        document_id: int | None = None,
    ) -> dict:
        if word_ids:
            ids = list(word_ids)
        else:
            purpose = "mistakes" if mistakes_only else "due"
            ids = self.store.pick_word_ids(
                purpose=purpose,
                limit=max(limit * 3, limit),
                deck_id=deck_id,
                document_id=document_id,
            )
        return self._open("review", mode, ids, limit, document_id, deck_id, require_question=mode != "card")

    def answer(
        self,
        session_id: int,
        item: dict,
        *,
        result: str | None,
        rating: str | None,
        chosen: str | None,
        desired_retention: float = 0.9,
        leech_threshold: int = 8,
    ) -> dict:
        session = self.store.get_session(session_id)
        if not session:
            raise ValueError("学习会话不存在")
        before = self.store.load_state(item["word_id"])
        now = now_local()
        kind = session["kind"]
        if kind == "placement":
            if result not in _PLACEMENT_RATING:
                raise ValueError("无效的摸底结果")
            after = apply_placement(before, result, now)
            rating = _PLACEMENT_RATING[result]
            correct_flag = 1 if result == "correct" else 0 if result in {"wrong", "unknown"} else None
        else:
            if result == "wrong":
                rating = RATING_AGAIN
            if rating not in {RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_EASY, RATING_MASTERED}:
                raise ValueError("无效的熟悉度")
            after = apply_rating(
                before,
                rating,
                now,
                touch_learned=(kind == "learn"),
                desired_retention=desired_retention,
                leech_threshold=leech_threshold,
            )
            correct_flag = 0 if rating == RATING_AGAIN else 1
            if result is None:
                result = "wrong" if rating == RATING_AGAIN else "correct"
        log_id = self.store.save_answer(
            session_id=session_id,
            item_id=item["id"],
            word_id=item["word_id"],
            result=result,
            rating=rating,
            chosen=chosen,
            correct_gloss=item.get("correct_gloss") or "",
            state_before=before,
            state_after=after,
            mode=kind,
            correct_flag=correct_flag,
        )
        return {"log_id": log_id, "state_before": before, "state_after": after, "rating": rating, "result": result}

    def amend(
        self,
        log_id: int,
        word_id: int,
        state_before,
        rating: str,
        *,
        kind: str,
        when: datetime,
        desired_retention: float = 0.9,
        leech_threshold: int = 8,
    ) -> None:
        after = apply_rating(
            state_before,
            rating,
            when,
            touch_learned=(kind == "learn"),
            desired_retention=desired_retention,
            leech_threshold=leech_threshold,
        )
        flag = 0 if rating == RATING_AGAIN else 1
        self.store.amend_answer(log_id, word_id, after, rating, flag)

    def undo_last(self) -> dict | None:
        return self.store.undo_last_review()

    def abandon(self, session_id: int) -> None:
        self.store.abandon_session(session_id)

    def report(self, session_id: int) -> dict:
        session = self.store.get_session(session_id)
        items = self.store.session_items(session_id)
        counts = Counter(item["result"] for item in items if item["result"])
        graded = counts["correct"] + counts["wrong"] + counts["unknown"]
        wrong_items = [item for item in items if item["result"] in {"wrong", "unknown"}]
        wrong_items.sort(key=lambda item: self.store.frequency_of(item["word_id"]), reverse=True)
        return {
            "session": session,
            "total": sum(counts.values()),
            "correct": counts["correct"],
            "wrong": counts["wrong"],
            "unknown": counts["unknown"],
            "skip": counts["skip"],
            "mastered": counts["mastered"],
            "accuracy": round((counts["correct"] / graded * 100) if graded else 0, 1),
            "learning_ids": [item["word_id"] for item in wrong_items],
            "frequent_wrong": [
                {
                    "lemma": item["lemma"],
                    "gloss": item.get("correct_gloss") or "",
                    "frequency": self.store.frequency_of(item["word_id"]),
                }
                for item in wrong_items[:8]
            ],
        }

    def _open(self, kind, mode, ids, limit, document_id, deck_id, require_question: bool) -> dict:
        items = []
        skipped = 0
        for word_id in ids:
            if len(items) >= limit:
                break
            question = self._make(word_id, mode if kind != "placement" else "quiz", document_id)
            if question is None:
                skipped += 1
                if require_question:
                    continue
            if question is None:
                continue
            items.append(
                {
                    "word_id": question.word_id,
                    "sense_id": question.sense_id,
                    "pos": question.pos,
                    "correct": question.correct,
                    "options": question.options,
                    "example": question.example,
                }
            )
        if not items:
            if not ids and kind == "learn" and document_id:
                message = "这份文档的学习计划里，没有还没学过的单词。"
            elif not ids:
                message = "当前没有符合条件的单词。"
            elif mode == "cloze":
                message = "这些单词在你的文章里没有可用例句，没有编造句子。"
            elif require_question:
                message = "这些单词缺少可靠的中文释义，无法生成不会产生歧义的题目。请先在生词本里补充释义。"
            else:
                message = "当前没有可学习的单词。"
            return {"session_id": None, "queued": 0, "skipped": skipped, "message": message}
        session_id = self.store.create_session(kind, mode, document_id, deck_id, items)
        message = ""
        if skipped:
            if mode == "cloze":
                message = f"有 {skipped} 个单词在你的文章里没有可用例句，没有编造句子。"
            elif mode == "listen":
                message = f"有 {skipped} 个单词缺少可靠释义，没有出听音题。"
            else:
                message = f"有 {skipped} 个单词因缺少可靠释义被跳过，没有编造选项。"
        return {"session_id": session_id, "queued": len(items), "skipped": skipped, "message": message}

    def _make(self, word_id: int, mode: str, document_id: int | None) -> Question | None:
        senses = self.store.senses_of(word_id)
        examples = self.store.examples_of(word_id, document_id)
        example = examples[0]["sentence"] if examples else None
        if mode == "cloze":
            word = self.store._one("SELECT lemma FROM words WHERE id = ?", (word_id,))
            lemma = word["lemma"] if word else ""
            surfaces = [row["surface"] for row in self.store.sources_of(word_id)]
            blank = blank_sentence(example or "", [lemma, *surfaces])
            if not blank or not lemma:
                return None
            return Question(word_id=word_id, sense_id=None, pos="", correct=lemma, options=[], example=blank)
        if mode == "listen":
            return self.quiz.build(word_id=word_id, senses=senses, example=example)
        if mode in {"quiz", "placement"}:
            return self.quiz.build(word_id=word_id, senses=senses, example=example)
        primary = next((sense for sense in senses if sense.get("is_primary")), senses[0] if senses else None)
        gloss = short_gloss(primary["gloss_zh"]) if primary else None
        if mode == "spell" and not gloss:
            return None
        return Question(
            word_id=word_id,
            sense_id=primary["id"] if primary else None,
            pos=(primary or {}).get("pos") or "",
            correct=gloss or "",
            options=[],
            example=example,
        )
