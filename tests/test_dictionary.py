from wordflow.dictionary import Dictionary
from tests.support import write_dictionary


def test_glossed_headword_stays_independent_of_exchange_parent(tmp_path):
    path = tmp_path / "dict.db"
    write_dictionary(path)
    connection_path = path
    import sqlite3

    connection = sqlite3.connect(connection_path)
    connection.execute(
        """
        INSERT INTO stardict(id, word, phonetic, definition, translation, pos, collins, oxford, frq, exchange)
        VALUES (900, 'mean', 'miːn', 'not generous', 'adj. 吝啬的；平均的', 'adj', 1, 1, 100, '')
        """
    )
    connection.execute(
        """
        INSERT INTO stardict(id, word, phonetic, definition, translation, pos, collins, oxford, frq, exchange)
        VALUES (901, 'meaning', 'ˈmiːnɪŋ', 'what is meant', 'n. 意义；含义', 'n', 1, 1, 200, '0:mean')
        """
    )
    connection.commit()
    connection.close()

    dictionary = Dictionary(path)
    assert dictionary.resolve_lemma("meaning") == "meaning"
    assert dictionary.resolve_lemma("running") == "run"
    assert dictionary.resolve_lemma("studies") == "study"
    meaning = dictionary.lookup("meaning")
    assert meaning is not None and meaning.senses[0].gloss_zh.startswith("意义")
    dictionary.close()
