from pathlib import Path

from wordflow.dictionary import Dictionary
from wordflow.quiz import QuizBuilder
from tests.support import write_dictionary


def _builder(tmp_path: Path) -> QuizBuilder:
    path = tmp_path / "dict.db"
    write_dictionary(path)
    return QuizBuilder(Dictionary(path))


def test_question_has_one_real_answer_and_no_conflicting_options(tmp_path):
    builder = _builder(tmp_path)
    senses = [
        {"id": 1, "pos": "v", "gloss_zh": "放弃；抛弃", "is_primary": 1},
        {"id": 2, "pos": "n", "gloss_zh": "放任", "is_primary": 0},
    ]
    positions = set()
    for _ in range(12):
        question = builder.build(word_id=1, senses=senses, example="He had to abandon the plan.")
        assert question is not None
        assert question.options.count(question.correct) == 1
        assert len(question.options) == 4
        assert question.correct == "放弃；抛弃"
        assert "放任" not in question.options
        for option in question.options:
            assert "放弃" not in option or option == question.correct
            assert "抛弃" not in option or option == question.correct
        positions.add(question.options.index(question.correct))
    assert len(positions) > 1


def test_missing_gloss_does_not_invent_a_question(tmp_path):
    builder = _builder(tmp_path)
    assert builder.build(word_id=2, senses=[], example=None) is None
    assert builder.build(word_id=3, senses=[{"id": 1, "pos": "n", "gloss_zh": "TODO", "is_primary": 1}], example=None) is None
