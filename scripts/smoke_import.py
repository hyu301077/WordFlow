"""用真实词典和一篇 TED 文稿做一次导入与出题检查。"""

import tempfile
from pathlib import Path

from wordflow.dictionary import Dictionary
from wordflow.extract import ExtractOptions
from wordflow.importer import Importer
from wordflow.quiz import QuizBuilder
from wordflow.store import Store

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    dictionary = Dictionary(ROOT / "data" / "ecdict.db")
    store = Store(Path(tempfile.mkdtemp()) / "smoke.db")
    importer = Importer(store, dictionary, ExtractOptions())
    sample = ROOT.parent / "英语学习" / "talks" / "人生不只是要快乐" / "output" / "ted_english.md"
    if not sample.is_file():
        raise SystemExit(f"找不到示例文稿：{sample}")
    result = importer.import_file(sample, kind="article")
    print("status", result.status, "unique", result.unique_words, "tokens", result.total_tokens)
    for lemma in ("happy", "meaning", "mean", "purpose", "running", "run"):
        word = store.get_word_by_lemma(lemma)
        if not word:
            print(lemma, "not in article or filtered")
            continue
        senses = store.senses_of(word["id"])
        gloss = senses[0]["gloss_zh"][:48] if senses else "待补充"
        print(lemma, word["phonetic"], gloss)
    builder = QuizBuilder(dictionary)
    checked = 0
    for word_id in store.pick_word_ids(purpose="untested", limit=40):
        question = builder.build(word_id=word_id, senses=store.senses_of(word_id), example=None)
        if question is None:
            continue
        if question.options.count(question.correct) != 1 or len(question.options) != 4:
            raise SystemExit(f"bad question {question}")
        checked += 1
        if checked >= 8:
            break
    print("quiz_ok", checked)
    store.close()
    dictionary.close()


if __name__ == "__main__":
    main()
