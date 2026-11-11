from datetime import datetime, timedelta, timezone

from wordflow.constants import STATUS_LEARNING, STATUS_MASTERED, STATUS_PENDING, STATUS_REVIEWING
from wordflow.srs import MemoryState, apply_manual_status, apply_placement, apply_rating

NOW = datetime(2026, 1, 1, 9, 0, tzinfo=timezone(timedelta(hours=8)))


def test_good_answers_follow_fsrs_and_are_deterministic():
    state = apply_rating(MemoryState(), "good", NOW)
    assert state.status == STATUS_LEARNING
    assert state.fsrs_state == "learning"
    assert state.repetitions == 0
    assert state.stability > 0
    assert 9 * 60 <= (state.next_review_at - NOW).total_seconds() <= 11 * 60
    again = apply_rating(MemoryState(), "good", NOW)
    assert abs(again.interval_days - state.interval_days) < 1e-9
    state = apply_rating(state, "good", state.next_review_at)
    assert state.fsrs_state == "review"
    assert state.status == STATUS_REVIEWING
    assert state.repetitions == 1
    assert state.interval_days > 10 / 1440
    previous = state.interval_days
    state = apply_rating(state, "good", state.next_review_at)
    assert state.interval_days > previous
    assert state.stability > 0


def test_failure_and_mastered_lapse():
    state = apply_rating(
        MemoryState(
            status=STATUS_MASTERED,
            repetitions=5,
            interval_days=30,
            stability=30,
            difficulty=5,
            fsrs_state="review",
        ),
        "again",
        NOW,
    )
    assert state.status == STATUS_LEARNING
    assert state.fsrs_state == "relearning"
    assert state.repetitions == 0
    assert state.lapses == 1
    assert state.wrong_count == 1
    assert (state.next_review_at - NOW).total_seconds() < 20 * 60


def test_placement_does_not_treat_one_correct_answer_as_mastered():
    state = apply_placement(MemoryState(), "correct", NOW)
    assert state.status == STATUS_REVIEWING
    assert state.mastery == 40
    assert abs(state.interval_days - 1) < 0.01
    wrong = apply_placement(MemoryState(), "wrong", NOW)
    assert wrong.status == STATUS_LEARNING
    unknown = apply_placement(MemoryState(), "unknown", NOW)
    assert unknown.status == STATUS_LEARNING
    skipped = apply_placement(MemoryState(), "skip", NOW)
    assert skipped.status == STATUS_PENDING
    mastered = apply_placement(MemoryState(), "mastered", NOW)
    assert mastered.status == STATUS_MASTERED


def test_manual_move_is_exclusive():
    learning = apply_manual_status(MemoryState(status=STATUS_MASTERED, mastery=95), "learning", NOW)
    assert learning.status == STATUS_LEARNING
    assert learning.mastery <= 30
    back = apply_manual_status(learning, "mastered", NOW)
    assert back.status == STATUS_MASTERED
    assert back.mastery >= 92
