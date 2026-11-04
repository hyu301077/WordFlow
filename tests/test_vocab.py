from wordflow.dictionary import Dictionary
from wordflow.store import Store
from wordflow.vocab import add_manual_word, batch_add, export_csv, import_table, move_words
from tests.support import write_dictionary


def test_manual_word_survives_restart_and_has_one_status(tmp_path):
    dictionary_path = tmp_path / "dict.db"
    write_dictionary(dictionary_path)
    db_path = tmp_path / "app.db"
    store = Store(db_path)
    dictionary = Dictionary(dictionary_path)
    word_id, created = add_manual_word(store, dictionary, text="banana", gloss_zh="香蕉", pos="n", status="learning")
    assert created
    assert store.senses_of(word_id)[0]["gloss_zh"] == "香蕉"
    store.close()
    dictionary.close()

    store = Store(db_path)
    dictionary = Dictionary(dictionary_path)
    kept = store.get_word_by_lemma("banana")
    assert kept
    assert store.load_state(kept["id"]).status == "learning"
    move_words(store, [kept["id"]], "mastered")
    assert store.load_state(kept["id"]).status == "mastered"
    learning, _total = store.list_words(statuses=("learning", "reviewing"))
    mastered, _total = store.list_words(statuses=("mastered",))
    assert all(row["id"] != kept["id"] for row in learning)
    assert any(row["id"] == kept["id"] for row in mastered)

    result = batch_add(store, dictionary, "apple\napple\n123bad", "learning")
    assert result["added"] == 1
    assert result["existed"] == 1
    assert result["invalid"] == 1
    apple = store.get_word_by_lemma("apple")
    assert any("苹果" in sense["gloss_zh"] for sense in store.senses_of(apple["id"]))
    path = tmp_path / "words.csv"
    export_csv(path, store.export_rows())
    imported = import_table(store, dictionary, path)
    assert imported["updated"] >= 1
    store.close()
    dictionary.close()
