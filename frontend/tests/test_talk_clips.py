import json
import wave
from pathlib import Path

from wordflow.listen import list_clips
from wordflow.talk_clips import (
    Segment,
    Span,
    TimedWord,
    align_sentences,
    export_mp3s,
    merge_short_spans,
    parse_translations,
    split_sentences,
    write_pack,
)


def test_split_keeps_titles_and_short_utterances():
    sentences = split_sentences("Dr. Smith met J. K. Rowling. Yes! Enormous.")
    assert sentences == ["Dr. Smith met J. K. Rowling.", "Yes!", "Enormous."]
    assert split_sentences("She lived in the U.S. for years.") == ["She lived in the U.S. for years."]


def test_align_sentences_uses_word_times():
    words = [
        TimedWord("Hello", 0.2, 0.6),
        TimedWord("world.", 0.7, 1.1),
        TimedWord("Yes!", 1.8, 2.1),
    ]
    spans = align_sentences(["Hello world.", "Yes!"], words, margin=0.05)
    assert [span.text for span in spans] == ["Hello world.", "Yes!"]
    assert abs(spans[0].start - 0.15) < 0.001
    assert abs(spans[0].end - 1.15) < 0.001
    assert abs(spans[1].start - 1.75) < 0.001


def test_merge_absorbs_short_clips_into_the_shorter_neighbor():
    spans = [
        Span(0, 5, "This is a fairly long sentence here."),
        Span(5, 5.4, "Yes!"),
        Span(5.4, 10, "Another complete sentence follows."),
    ]
    merged, removed = merge_short_spans(spans)
    assert removed == 1
    assert len(merged) == 2
    assert merged[1].text == "Yes! Another complete sentence follows."
    assert merged[1].start == 5
    assert "merged-short" in merged[1].note


def test_merge_stops_when_only_one_clip_remains():
    spans = [Span(0, 0.4, "Hi."), Span(0.4, 0.8, "No."), Span(0.8, 1.1, "Yes.")]
    merged, removed = merge_short_spans(spans)
    assert len(merged) == 1
    assert removed == 2
    assert merged[0].text == "Hi. No. Yes."
    assert merged[0].start == 0
    assert merged[0].end == 1.1


def test_equal_neighbors_prefer_the_previous_clip():
    spans = [
        Span(0, 5, "Alpha beta gamma delta epsilon zeta eta theta."),
        Span(5, 6, "Oh no."),
        Span(6, 11, "Alpha beta gamma delta epsilon zeta eta theta."),
    ]
    merged, _removed = merge_short_spans(spans, second_limit=0.5)
    assert len(merged) == 2
    assert merged[0].text.startswith("Alpha")
    assert merged[0].text.endswith("Oh no.")
    assert merged[0].end == 6


def test_documents_mark_missing_translation_and_feed_listen_index(tmp_path: Path):
    folder = tmp_path / "talk"
    spans = [Span(0.1, 4.4, "Hello world.", "")]
    write_pack(folder, "示例", ["Hello world."], spans, ["待补充"], translated=False)
    english = (folder / "output" / "ted_english.md").read_text(encoding="utf-8")
    bilingual = (folder / "output" / "ted_bilingual.md").read_text(encoding="utf-8")
    assert "Hello world." in english
    assert "[001]" not in english
    assert "[001]" in bilingual
    assert "待补充" in bilingual
    assert (folder / "output" / "ted_english.docx").is_file()
    rows = json.loads((folder / "sentences_by_sentence" / "index.json").read_text(encoding="utf-8"))
    assert rows[0]["id"] == "001"
    assert rows[0]["text"] == "Hello world."
    clip = folder / "sentences_by_sentence" / "001.mp3"
    clip.write_bytes(b"not-audio")
    listed = list_clips(folder / "sentences_by_sentence")
    assert listed[0]["text"] == "Hello world."
    assert listed[0]["duration"] == 4.3


def test_parse_translations_leaves_unknown_lines_blank():
    text = "[001] 你好。\n没有编号的一句\n[003] 待补充"
    assert parse_translations(text, 0, 3) == ["你好。", "待补充", "待补充"]


def test_export_mp3_cuts_a_wav(tmp_path: Path):
    wav_path = tmp_path / "talk.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\x00\x00" * 44100)
    export_mp3s(wav_path, [Span(0.1, 0.6, "Hello.")], tmp_path / "clips")
    output = tmp_path / "clips" / "001.mp3"
    assert output.is_file()
    assert output.stat().st_size > 100


def test_paragraphs_break_on_a_pause():
    from wordflow.talk_clips import paragraph_groups

    groups = paragraph_groups(
        [
            Segment("First sentence.", 0, 1),
            Segment("Still the same paragraph.", 1.2, 2),
            Segment("A later paragraph.", 4, 5),
        ]
    )
    assert groups == ["First sentence. Still the same paragraph.", "A later paragraph."]
