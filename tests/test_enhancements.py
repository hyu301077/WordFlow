"""对照同类应用补上的复习、填空、听音和搭配。"""

from datetime import timedelta
from pathlib import Path

from wordflow.collocation import blank_sentence, phrases_in_sentences
from wordflow.constants import STATUS_LEARNING, STATUS_REVIEWING
from wordflow.dictionary import Dictionary
from wordflow.extract import ExtractOptions
from wordflow.gloss import norm_gloss
from wordflow.importer import Importer
from wordflow.srs import (
    MemoryState,
    apply_rating,
    format_interval,
    preview_intervals,
    retrievability,
)
from wordflow.store import Store
from wordflow.study import StudyService
from wordflow.timeutil import now_local, today_str

from tests.support import write_dictionary
from tests.test_srs import NOW


def test_blank_and_collocation_use_only_the_given_sentences():
    assert blank_sentence("He had to abandon his original plan.", ["abandon"]) == "He had to ______ his original plan."
    assert blank_sentence("The apple is red.", ["apple"]) is None or "______" in blank_sentence("The apple is red.", ["apple"])
    assert blank_sentence("No target here.", ["apple"]) is None
    lines = phrases_in_sentences(
        "abandon",
        [
            "He had to abandon his original plan.",
            "They abandon his original route.",
        ],
    )
    assert lines
    assert any("original" in line and "×2" in line for line in lines)


def test_higher_retention_shortens_a_review_interval_and_leech_is_tagged():
    mature = MemoryState(
        status=STATUS_REVIEWING,
        stability=10,
        difficulty=5,
        fsrs_state="review",
        repetitions=3,
        interval_days=10,
        last_review_at=NOW - timedelta(days=10),
    )
    low = apply_rating(mature, "good", NOW, desired_retention=0.80)
    high = apply_rating(mature, "good", NOW, desired_retention=0.95)
    assert high.interval_days < low.interval_days
    fresh = apply_rating(MemoryState(), "good", NOW, desired_retention=0.95)
    same = apply_rating(MemoryState(), "good", NOW, desired_retention=0.80)
    assert abs(fresh.interval_days - same.interval_days) < 1e-9

    state = mature
    for _ in range(7):
        state = apply_rating(state, "again", NOW, leech_threshold=8)
    assert state.lapses == 7
    assert state.leech == 0
    state = apply_rating(state, "again", NOW, leech_threshold=8)
    assert state.lapses == 8
    assert state.leech == 1
    kept = apply_rating(state, "good", state.next_review_at, leech_threshold=8)
    assert kept.leech == 1


def test_preview_again_is_sooner_than_good_and_retrievability_is_real():
    mature = MemoryState(
        status=STATUS_REVIEWING,
        stability=20,
        difficulty=5,
        fsrs_state="review",
        repetitions=3,
        interval_days=20,
        last_review_at=NOW - timedelta(days=5),
    )
    again = apply_rating(mature, "again", NOW)
    good = apply_rating(mature, "good", NOW)
    assert again.interval_days < good.interval_days
    labels = preview_intervals(mature, NOW)
    assert labels["again"] != labels["good"]
    assert "分钟" in labels["again"] or "小时" in labels["again"] or "天" in labels["again"]
    assert format_interval(good.interval_days)
    reviewed = apply_rating(mature, "good", NOW)
    chance = retrievability(reviewed, NOW)
    assert chance is not None
    assert 0 < chance <= 1
    assert retrievability(MemoryState(), NOW) is None


def test_undo_forecast_cloze_listen_and_leech_queue(tmp_path: Path):
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    store = Store(tmp_path / "app.db")
    dictionary = Dictionary(dictionary_path)
    story = tmp_path / "story.md"
    story.write_text(
        "He had to abandon his original plan.\nThey abandon his original route.\nThe apple is running across the bank.\n",
        encoding="utf-8",
    )
    Importer(store, dictionary, ExtractOptions()).import_file(story, kind="article")
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 3
    service = StudyService(store, dictionary)
    abandon = store.get_word_by_lemma("abandon")
    apple = store.get_word_by_lemma("apple")
    bank = store.get_word_by_lemma("bank")
    assert abandon and apple and bank

    cloze = service.start_learn(mode="cloze", limit=1, document_id=None, deck_id=None, word_ids=[abandon["id"]])
    cloze_item = store.session_items(cloze["session_id"])[0]
    assert "______" in cloze_item["example"]
    assert "abandon" not in cloze_item["example"].lower()
    idea = dictionary.lookup("idea")
    idea_id = store.ensure_word("idea", "idea", idea)
    missing = service.start_learn(mode="cloze", limit=1, document_id=None, deck_id=None, word_ids=[idea_id])
    assert missing["session_id"] is None

    listen = service.start_learn(mode="listen", limit=1, document_id=None, deck_id=None, word_ids=[abandon["id"]])
    heard = store.session_items(listen["session_id"])[0]
    assert len(heard["options"]) == 4
    assert sum(norm_gloss(option) == norm_gloss(heard["correct_gloss"]) for option in heard["options"]) == 1

    opened = service.start_learn(mode="card", limit=1, document_id=None, deck_id=None, word_ids=[apple["id"]])
    item = store.session_items(opened["session_id"])[0]
    before = store.load_state(apple["id"])
    service.answer(opened["session_id"], item, result="correct", rating="good", chosen=None)
    assert store.load_state(apple["id"]).correct_count == before.correct_count + 1
    studied = store._one("SELECT correct FROM daily_stats WHERE day = ?", (today_str(),))
    undone = service.undo_last()
    assert undone["lemma"] == "apple"
    restored = store.load_state(apple["id"])
    assert restored.status == before.status
    assert restored.lapses == before.lapses
    assert restored.correct_count == before.correct_count
    log = store._one("SELECT undone FROM review_logs ORDER BY id DESC LIMIT 1")
    assert log["undone"] == 1
    after_undo = store._one("SELECT correct FROM daily_stats WHERE day = ?", (today_str(),))
    assert after_undo["correct"] == max(0, studied["correct"] - 1)

    today = now_local()
    overdue = store.load_state(apple["id"])
    overdue.next_review_at = today - timedelta(days=1)
    overdue.leech = 1
    store.save_state(apple["id"], overdue)
    later = store.load_state(bank["id"])
    later.next_review_at = today + timedelta(days=3)
    later.leech = 0
    store.save_state(bank["id"], later)
    forecast = store.due_forecast(7)
    assert forecast[0]["count"] >= 1
    assert forecast[3]["count"] >= 1
    due = store.pick_word_ids(purpose="due", limit=5)
    assert due[0] == apple["id"]
    rows, total = store.list_words(leeches_only=True, limit=20)
    assert total >= 1
    assert any(row["id"] == apple["id"] for row in rows)
    store.close()
    dictionary.close()
