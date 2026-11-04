"""间隔重复。

调度使用官方 py-fsrs 的 FSRS-6，保留率 0.9，学习间隔为 1 分钟和 10 分钟，
答错后的重学间隔为 10 分钟，最长间隔 365 天。关闭了随机模糊，同一回答得到的
下次时间是确定的。

摸底答对只记为初步认识，不会因此变成已掌握。用户明确标记「已熟练掌握」时，
间隔至少为 21 天。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, Scheduler, State

from wordflow.constants import (
    RATING_AGAIN,
    RATING_EASY,
    RATING_GOOD,
    RATING_HARD,
    RATING_MASTERED,
    STATUS_LEARNING,
    STATUS_MASTERED,
    STATUS_PENDING,
    STATUS_REVIEWING,
    STATUS_UNTESTED,
)
from wordflow.timeutil import add_days

SHORT_STEP_DAYS = 10 / 1440
MASTERED_INTERVAL = 21.0

_SCHEDULER = Scheduler(
    desired_retention=0.9,
    learning_steps=(timedelta(minutes=1), timedelta(minutes=10)),
    relearning_steps=(timedelta(minutes=10),),
    maximum_interval=365,
    enable_fuzzing=False,
)

_RATINGS = {
    RATING_AGAIN: Rating.Again,
    RATING_HARD: Rating.Hard,
    RATING_GOOD: Rating.Good,
    RATING_EASY: Rating.Easy,
    RATING_MASTERED: Rating.Easy,
}


@dataclass
class MemoryState:
    status: str = STATUS_UNTESTED
    mastery: int = 0
    ease: float = 2.5
    interval_days: float = 0.0
    repetitions: int = 0
    lapses: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    skip_count: int = 0
    streak: int = 0
    next_review_at: datetime | None = None
    last_review_at: datetime | None = None
    last_learned_at: datetime | None = None
    manual_override: int = 0
    notes: str = ""
    stability: float = 0.0
    difficulty: float = 0.0
    fsrs_state: str = "new"
    fsrs_step: int = 0

    def copy(self) -> "MemoryState":
        return replace(self)


def apply_rating(
    state: MemoryState,
    rating: str,
    now: datetime,
    *,
    touch_learned: bool = False,
) -> MemoryState:
    if rating not in _RATINGS:
        raise ValueError(f"未知的熟悉度：{rating}")
    review_at = _as_utc(now)
    card, _log = _SCHEDULER.review_card(_to_card(state, now), _RATINGS[rating], review_at)
    if rating == RATING_MASTERED:
        card.state = State.Review
        card.step = None
        if (card.stability or 0) < MASTERED_INTERVAL:
            card.stability = MASTERED_INTERVAL
        if card.due < review_at + timedelta(days=MASTERED_INTERVAL):
            card.due = review_at + timedelta(days=MASTERED_INTERVAL)

    nxt = state.copy()
    nxt.manual_override = 0
    nxt.last_review_at = now
    if touch_learned:
        nxt.last_learned_at = now
    nxt.stability = float(card.stability or 0)
    nxt.difficulty = float(card.difficulty or nxt.difficulty or 0)
    nxt.ease = round(nxt.difficulty or nxt.ease, 4)
    nxt.fsrs_state = _state_name(card.state)
    nxt.fsrs_step = 0 if card.step is None else int(card.step)
    nxt.interval_days = max(0.0, (card.due - review_at).total_seconds() / 86400)
    nxt.next_review_at = _from_utc(card.due, now)

    if rating == RATING_AGAIN:
        forgot = nxt.repetitions > 0 or state.status in {STATUS_REVIEWING, STATUS_MASTERED} or state.fsrs_state in {
            "review",
            "relearning",
        }
        nxt.repetitions = 0
        nxt.streak = 0
        nxt.wrong_count += 1
        if forgot:
            nxt.lapses += 1
        nxt.mastery = _clamp(nxt.mastery - 18)
        nxt.status = STATUS_LEARNING
        return nxt

    nxt.correct_count += 1
    nxt.streak += 1
    if card.state == State.Review:
        nxt.repetitions += 1
    if rating == RATING_HARD:
        nxt.mastery = _clamp(nxt.mastery + 5)
    elif rating == RATING_GOOD:
        nxt.mastery = _clamp(nxt.mastery + 12)
    elif rating == RATING_MASTERED:
        nxt.mastery = max(92, _clamp(nxt.mastery + 20))
    else:
        nxt.mastery = _clamp(nxt.mastery + 18)

    if rating == RATING_MASTERED:
        nxt.status = STATUS_MASTERED
    elif card.state != State.Review:
        nxt.status = STATUS_LEARNING
    elif state.status == STATUS_MASTERED and nxt.interval_days >= MASTERED_INTERVAL:
        nxt.status = STATUS_MASTERED
    elif nxt.repetitions >= 5 and nxt.interval_days >= MASTERED_INTERVAL and nxt.mastery >= 85:
        nxt.status = STATUS_MASTERED
    else:
        nxt.status = STATUS_REVIEWING
    return nxt


def apply_placement(state: MemoryState, outcome: str, now: datetime) -> MemoryState:
    nxt = state.copy()
    nxt.last_review_at = now
    nxt.manual_override = 0
    if outcome == "correct":
        nxt.status = STATUS_REVIEWING
        nxt.mastery = max(nxt.mastery, 40)
        nxt.repetitions = max(nxt.repetitions, 1)
        nxt.interval_days = 1
        nxt.stability = max(nxt.stability, 1.0)
        nxt.difficulty = nxt.difficulty or 5.0
        nxt.ease = round(nxt.difficulty, 4)
        nxt.fsrs_state = "review"
        nxt.fsrs_step = 0
        nxt.correct_count += 1
        nxt.streak += 1
        nxt.next_review_at = add_days(now, 1)
        return nxt
    if outcome in {"wrong", "unknown"}:
        nxt.status = STATUS_LEARNING
        nxt.mastery = 5 if outcome == "unknown" else 8
        nxt.repetitions = 0
        nxt.interval_days = SHORT_STEP_DAYS
        nxt.stability = 0
        nxt.difficulty = 0
        nxt.fsrs_state = "new"
        nxt.fsrs_step = 0
        nxt.streak = 0
        nxt.wrong_count += 1
        nxt.next_review_at = add_days(now, SHORT_STEP_DAYS)
        return nxt
    if outcome == "skip":
        nxt.status = STATUS_PENDING
        nxt.skip_count += 1
        nxt.next_review_at = None
        return nxt
    if outcome == "mastered":
        nxt.status = STATUS_MASTERED
        nxt.mastery = max(nxt.mastery, 92)
        nxt.repetitions = max(nxt.repetitions, 4)
        nxt.interval_days = max(nxt.interval_days, MASTERED_INTERVAL)
        nxt.stability = max(nxt.stability, MASTERED_INTERVAL)
        nxt.difficulty = nxt.difficulty or 5.0
        nxt.ease = round(nxt.difficulty, 4)
        nxt.fsrs_state = "review"
        nxt.fsrs_step = 0
        nxt.correct_count += 1
        nxt.streak += 1
        nxt.next_review_at = add_days(now, nxt.interval_days)
        return nxt
    raise ValueError(f"未知的摸底结果：{outcome}")


def apply_manual_status(state: MemoryState, status: str, now: datetime) -> MemoryState:
    nxt = state.copy()
    nxt.manual_override = 1
    nxt.status = status
    if status == STATUS_MASTERED:
        nxt.mastery = max(nxt.mastery, 92)
        nxt.repetitions = max(nxt.repetitions, 4)
        nxt.interval_days = max(MASTERED_INTERVAL, nxt.interval_days or MASTERED_INTERVAL)
        nxt.stability = max(MASTERED_INTERVAL, nxt.stability or 0)
        nxt.difficulty = nxt.difficulty or 5.0
        nxt.ease = round(nxt.difficulty, 4)
        nxt.fsrs_state = "review"
        nxt.fsrs_step = 0
        nxt.next_review_at = add_days(now, nxt.interval_days)
    elif status == STATUS_LEARNING:
        nxt.repetitions = 0
        nxt.interval_days = 0
        nxt.stability = 0
        nxt.difficulty = 0
        nxt.fsrs_state = "new"
        nxt.fsrs_step = 0
        nxt.last_learned_at = None
        nxt.mastery = min(nxt.mastery, 30)
        nxt.next_review_at = add_days(now, SHORT_STEP_DAYS)
    elif status == STATUS_REVIEWING:
        nxt.interval_days = max(1.0, nxt.interval_days or 1.0)
        nxt.stability = max(1.0, nxt.stability or nxt.interval_days)
        nxt.difficulty = nxt.difficulty or 5.0
        nxt.ease = round(nxt.difficulty, 4)
        nxt.fsrs_state = "review"
        nxt.fsrs_step = 0
        nxt.repetitions = max(nxt.repetitions, 1)
        nxt.next_review_at = add_days(now, nxt.interval_days)
    elif status == STATUS_PENDING:
        nxt.fsrs_state = "new"
        nxt.next_review_at = None
    elif status == STATUS_UNTESTED:
        nxt.fsrs_state = "new"
        nxt.fsrs_step = 0
        nxt.stability = 0
        nxt.difficulty = 0
        nxt.next_review_at = None
        nxt.repetitions = 0
        nxt.interval_days = 0
    else:
        raise ValueError(f"未知的词汇状态：{status}")
    return nxt


def _to_card(state: MemoryState, now: datetime) -> Card:
    due = _as_utc(state.next_review_at or now)
    fresh = state.stability <= 0 or state.fsrs_state in {"", "new"}
    if fresh:
        return Card(card_id=1, state=State.Learning, step=0, stability=None, difficulty=None, due=due, last_review=None)
    mapped = {"learning": State.Learning, "review": State.Review, "relearning": State.Relearning}.get(
        state.fsrs_state, State.Learning
    )
    step = None if mapped == State.Review else int(state.fsrs_step or 0)
    difficulty = state.difficulty if state.difficulty > 0 else 5.0
    last = _as_utc(state.last_review_at) if state.last_review_at else None
    return Card(
        card_id=1,
        state=mapped,
        step=step,
        stability=state.stability,
        difficulty=difficulty,
        due=due,
        last_review=last,
    )


def _state_name(value: State) -> str:
    return {State.Learning: "learning", State.Review: "review", State.Relearning: "relearning"}[value]


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _from_utc(moment: datetime, reference: datetime) -> datetime:
    if reference.tzinfo is None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.astimezone(reference.tzinfo)


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))
