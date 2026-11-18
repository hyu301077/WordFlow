import os
from pathlib import Path

from wordflow.extract import ExtractOptions
from wordflow.importer import Importer
from wordflow.study import StudyService
from tests.support import write_dictionary


def test_placement_can_speak_sentence_at_two_speeds_and_file_the_word(tmp_path: Path):
    os.environ["WORDFLOW_DATA"] = str(tmp_path / "data")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QPushButton

    from wordflow.context import AppContext
    from wordflow.ui.study_widget import StudyWidget

    QApplication.instance() or QApplication([])
    dictionary = tmp_path / "dict.db"
    write_dictionary(dictionary)
    ctx = AppContext(db_path=tmp_path / "app.db", dict_path=dictionary)
    ctx.settings.set("auto_speak", "0")
    importer = Importer(ctx.store, ctx.dictionary, ExtractOptions())
    imported = importer.import_article("Sample", "The apple is on the bank.", "测试")
    study = StudyService(ctx.store, ctx.dictionary)
    started = study.start_placement(
        limit=5,
        document_id=imported.document_id,
        deck_id=None,
        include_pending=True,
    )
    widget = StudyWidget(ctx, started["session_id"])
    widget.show()
    QApplication.instance().processEvents()
    labels = [button.text() for button in widget.findChildren(QPushButton)]
    assert "朗读单词" in labels
    assert "朗读例句" in labels
    assert "1×" in labels
    assert "0.75×" in labels
    assert "不认识" in labels
    assert "加入生词本" in labels
    assert "加入熟词本" in labels
    assert widget.sentence_rate_buttons[1.0].isChecked()
    assert widget.speak_sentence.isVisible()

    example = widget.current["example"]
    assert example
    wav = tmp_path / "sentence.wav"
    wav.write_bytes(b"RIFF")
    spoken: list[str] = []

    def synthesize(text: str):
        spoken.append(text)
        return wav, ""

    played: list[tuple[str, float]] = []
    widget.ctx.speech.synthesize = synthesize
    widget.sentence_player.play_file = lambda path: played.append((path, widget.sentence_player.rate))
    widget._choose_sentence_rate(0.75, replay=False)
    widget._speak_sentence(True)
    assert spoken == [example]
    assert played == [(str(wav), 0.75)]
    assert ctx.settings.get("placement_sentence_rate") == "0.75"

    widget._choose_sentence_rate(1.0, replay=False)
    widget._speak_sentence(True)
    assert spoken == [example]
    assert played[-1] == (str(wav), 1.0)

    widget._placement("unknown")
    assert widget.feedback.text().startswith("已加入生词本")
    assert ctx.store.load_state(widget.current["word_id"]).status == "learning"
    widget.sentence_player.stop()
    widget.deleteLater()
    ctx.close()


def _extra_labels(widget) -> list[str]:
    labels = []
    for index in range(widget.extra.count()):
        button = widget.extra.itemAt(index).widget()
        if button is not None:
            labels.append(button.text())
    return labels


def test_spelling_hides_the_answer_until_submission_and_ignores_arrow_keys(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from wordflow.context import AppContext
    from wordflow.ui.study_widget import StudyWidget

    monkeypatch.setenv("WORDFLOW_DATA", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    dictionary = tmp_path / "dict.db"
    write_dictionary(dictionary)
    ctx = AppContext(db_path=tmp_path / "app.db", dict_path=dictionary)
    ctx.settings.set("auto_speak", "0")
    word_id = ctx.store.ensure_word("apple", "apple", ctx.dictionary.lookup("apple"))
    item = {"word_id": word_id, "correct": "苹果", "example": "I ate an apple."}
    session = ctx.store.create_session("learn", "spell", None, None, [item])
    widget = StudyWidget(ctx, session)
    widget.show()
    app.processEvents()
    assert widget.word.text() == "拼写"
    assert widget.prompt.text() == "苹果"
    assert all(not label.text() for label in (widget.example, widget.phonetic, widget.phrases))
    widget.spell.setText("aple")
    QTest.keyClick(widget.spell, Qt.Key_Return)
    assert widget.word.text() == "apple"
    assert "正确拼写：apple" in widget.feedback.text()
    widget.close()
    session = ctx.store.create_session("learn", "card", None, None, [item])
    card = StudyWidget(ctx, session)
    card._reveal_card()
    QTest.keyClick(card, Qt.Key_Left)
    assert card.phase == "rate"
    assert ctx.store.session_items(session)[0]["result"] is None
    card.close()
    ctx.close()


def test_book_buttons_stay_after_the_answer(tmp_path: Path):
    os.environ["WORDFLOW_DATA"] = str(tmp_path / "data")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    from wordflow.context import AppContext
    from wordflow.extract import ExtractOptions
    from wordflow.importer import Importer
    from wordflow.study import StudyService
    from wordflow.ui.study_widget import StudyWidget

    QApplication.instance() or QApplication([])
    dictionary = tmp_path / "dict.db"
    write_dictionary(dictionary)
    ctx = AppContext(db_path=tmp_path / "app.db", dict_path=dictionary)
    ctx.settings.set("auto_speak", "0")
    imported = Importer(ctx.store, ctx.dictionary, ExtractOptions()).import_article(
        "Sample",
        "The apple is on the bank.",
        "测试",
    )
    started = StudyService(ctx.store, ctx.dictionary).start_placement(
        limit=5,
        document_id=imported.document_id,
        deck_id=None,
        include_pending=True,
    )
    widget = StudyWidget(ctx, started["session_id"])
    widget.show()
    QApplication.instance().processEvents()
    word_id = widget.current["word_id"]
    assert _extra_labels(widget) == ["不认识", "跳过", "加入生词本", "加入熟词本"]
    widget._choose(0)
    QApplication.instance().processEvents()
    assert widget.phase == "feedback"
    assert _extra_labels(widget) == ["加入生词本", "加入熟词本"]
    widget._placement("unknown")
    assert widget.feedback.text().startswith("已加入生词本")
    assert ctx.store.load_state(word_id).status == "learning"
    widget._placement("mastered")
    assert widget.feedback.text().startswith("已加入熟词本")
    assert ctx.store.load_state(word_id).status == "mastered"
    logs = ctx.store.conn.execute("SELECT COUNT(*) FROM review_logs WHERE word_id = ?", (word_id,)).fetchone()[0]
    assert logs == 1
    widget.sentence_player.stop()
    widget.deleteLater()
    ctx.close()
