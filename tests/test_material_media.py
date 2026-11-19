import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document

from wordflow import talk_clips as talk


LINES = ["Please open the window.", "We can hear the birds.", "Now close the window again."]


def recording(path):
    command = [talk.ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=15"]
    if path.suffix == ".mp4":
        command += ["-f", "lavfi", "-i", "color=size=16x16:rate=1:duration=15", "-c:v", "mpeg4", "-c:a", "aac"]
    subprocess.run([*command, str(path)], check=True, creationflags=talk._flags())


def fake_transcript(*args):
    return [talk.Segment(text, i * 5, (i + 1) * 5) for i, text in enumerate(LINES)], []


def rows(folder):
    return json.loads((folder / "sentences_by_sentence" / "index.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("extension", [".mp3", ".mp4"])
def test_prepare_resumes_original_audio_and_repairs_missing_assets(tmp_path, monkeypatch, extension):
    source = tmp_path / ("window lesson" + extension)
    recording(source)
    folder = tmp_path / "lesson"
    monkeypatch.setattr(talk, "transcribe_wav", fake_transcript)
    interrupted = False
    run = talk._run

    def run_first_clip(command):
        nonlocal interrupted
        run(command)
        if command[-1].endswith(".001.part"):
            interrupted = True

    monkeypatch.setattr(talk, "_run", run_first_clip)
    with pytest.raises(talk.TalkError, match="已取消"):
        talk.prepare_material_talk(source, folder, "small", tmp_path, cancelled=lambda: interrupted)
    clips = folder / "sentences_by_sentence"
    first_time = (clips / "001.mp3").stat().st_mtime_ns
    assert not (clips / "002.mp3").exists()

    def already_transcribed(*args):
        pytest.fail("不应重复识别已保存的音频")

    monkeypatch.setattr(talk, "transcribe_wav", already_transcribed)
    source.rename(source.with_stem("moved"))
    result = talk.prepare_material_talk(source, folder, "small", tmp_path)
    assert result.full_text == " ".join(LINES)
    assert result.pending_translations == 3
    assert not result.translated
    assert [row["text"] for row in rows(folder)] == LINES
    for row in rows(folder):
        assert abs(talk.media_duration(clips / row["file"]) - row["duration"]) < 0.2

    (clips / "002.mp3").unlink()
    (folder / "output" / "ted_bilingual.docx").unlink()
    talk.prepare_material_talk(source, folder, "small", tmp_path)
    assert (clips / "001.mp3").stat().st_mtime_ns == first_time
    assert (clips / "002.mp3").stat().st_size > 100
    assert (folder / "output" / "ted_bilingual.docx").is_file()
    (folder / "talk.wav").unlink()
    assert talk.prepare_material_talk(source, folder, "small", tmp_path).full_text == result.full_text
    (clips / "003.mp3").unlink()
    with pytest.raises(talk.TalkError, match="原始音视频"):
        talk.prepare_material_talk(source, folder, "small", tmp_path)


def test_enrich_checkpoints_partial_and_only_retries_missing_sentences(tmp_path, monkeypatch):
    source = tmp_path / "window.mp3"
    recording(source)
    monkeypatch.setattr(talk, "transcribe_wav", fake_transcript)
    folder = tmp_path / "lesson"
    talk.prepare_material_talk(source, folder, "small", tmp_path)
    clip = folder / "sentences_by_sentence" / "001.mp3"
    original_time = clip.stat().st_mtime_ns
    requests = []
    cancelled = False

    class Client:
        def complete(self, system, user, timeout):
            nonlocal cancelled
            requests.append(user)
            if len(requests) == 1:
                cancelled = True
                return "[001] 请打开窗户。\n[003] 现在再关上窗户。"
            if len(requests) == 2:
                raise RuntimeError("离线")
            return "[002] 我们可以听见鸟鸣。"

    client = Client()
    with pytest.raises(talk.TalkError, match="已取消"):
        talk.enrich_material_talk(folder, client, cancelled=lambda: cancelled)
    assert [row["translation"] for row in rows(folder)] == ["请打开窗户。", "待补充", "现在再关上窗户。"]
    partial = talk.enrich_material_talk(folder, client)
    assert partial.pending_translations == 1 and not partial.translated
    assert "离线" in partial.warning
    complete = talk.enrich_material_talk(folder, client)
    assert complete.translated and complete.pending_translations == 0
    assert requests[1:] == ["[002] We can hear the birds."] * 2
    assert clip.stat().st_mtime_ns == original_time
    assert rows(folder)[1]["translation"] == "我们可以听见鸟鸣。"
    assert "我们可以听见鸟鸣。" in (folder / "output" / "ted_bilingual.md").read_text(encoding="utf-8")
    docx = Document(folder / "output" / "ted_bilingual.docx")
    assert any("我们可以听见鸟鸣。" in paragraph.text for paragraph in docx.paragraphs)
    assert talk.enrich_material_talk(folder, client).translated
    assert len(requests) == 3


def test_open_word_export_does_not_block_plan_and_retries_on_close(tmp_path, monkeypatch):
    source = tmp_path / "window.mp3"
    recording(source)
    monkeypatch.setattr(talk, "transcribe_wav", fake_transcript)
    folder = tmp_path / "lesson"
    talk.prepare_material_talk(source, folder, "small", tmp_path)
    english = folder / "output" / "ted_english.docx"
    bilingual = folder / "output" / "ted_bilingual.docx"
    english_time = english.stat().st_mtime_ns
    locked = True
    replace = Path.replace

    def simulate_word(path, target):
        if target == bilingual and locked:
            raise PermissionError("sharing violation")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", simulate_word)
    class Client:
        def complete(self, *args, **kwargs):
            return "[001] 一。\n[002] 二。\n[003] 三。"

    done = talk.enrich_material_talk(folder, Client())
    assert done.translated and "ted_bilingual.docx" in done.warning
    assert done.full_text == " ".join(LINES)
    assert rows(folder)[1]["translation"] == "二。"
    assert "二。" in bilingual.with_suffix(".md").read_text(encoding="utf-8")
    locked = False
    assert not talk.prepare_material_talk(source, folder, "small", tmp_path).warning
    assert any("二。" in p.text for p in Document(bilingual).paragraphs)
    assert english.stat().st_mtime_ns == english_time
    exports = [*folder.joinpath("output").iterdir(), *folder.joinpath("sentences_by_sentence").iterdir()]
    times = {path: path.stat().st_mtime_ns for path in exports}
    talk.prepare_material_talk(source, folder, "small", tmp_path)
    assert all(path.stat().st_mtime_ns == mtime for path, mtime in times.items())


def test_transcribe_prefers_complete_offline_weights_and_explains_download_failure(tmp_path, monkeypatch):
    executable = tmp_path / "app" / "WordFlow.exe"
    bundled = executable.parent / "models" / "small"
    user = tmp_path / "user" / "models" / "small"
    bundled.mkdir(parents=True)
    user.mkdir(parents=True)
    for path in [bundled / "model.bin", bundled / "config.json", bundled / "tokenizer.json", user / "model.bin"]:
        path.write_bytes(b"fixture")
    chosen = []

    def whisper(name, **kwargs):
        chosen.append((name, kwargs["local_files_only"]))
        if name == "small":
            raise OSError("connection reset")
        segment = SimpleNamespace(text="Hello.", start=0, end=1, words=[])
        return SimpleNamespace(transcribe=lambda *args, **kw: ([segment], None))

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=whisper))
    monkeypatch.setattr(talk, "_whisper_audio", lambda wav, cancelled: [])
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    def transcribe():
        return talk.transcribe_wav(tmp_path / "talk.wav", "small", user.parent, lambda _: None, lambda: False)

    transcribe()
    assert chosen[-1] == (str(bundled), True)
    for name in ["config.json", "tokenizer.json"]:
        (user / name).write_bytes(b"fixture")
    transcribe()
    assert chosen[-1] == (str(user), True)
    (user / "config.json").unlink()
    (bundled / "config.json").unlink()
    with pytest.raises(talk.TalkError) as failed:
        transcribe()
    assert chosen[-1] == ("small", False)
    assert str(user) in str(failed.value) and str(bundled) in str(failed.value)


def test_whisper_audio_decodes_mono_float_pcm_and_reports_invalid_input(tmp_path):
    wav = tmp_path / "sample.wav"
    subprocess.run([talk.ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", "-ac", "2", "-ar", "44100", str(wav)], check=True)
    samples = talk._whisper_audio(wav, lambda: False)
    assert samples.dtype.name == "float32" and samples.shape == (16000,)
    assert 0 < samples.max() <= 1
    invalid = tmp_path / "invalid.wav"
    invalid.write_bytes(b"not a wave file")
    with pytest.raises(talk.TalkError, match="原声音频解码失败"):
        talk._whisper_audio(invalid, lambda: False)


def test_whisper_audio_cancels_active_decoder(tmp_path, monkeypatch):
    events = []

    class Decoder:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def communicate(self, timeout=None):
            if timeout:
                events.append("decoding")
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            events.append("drained")

        def kill(self):
            events.append("killed")

    monkeypatch.setattr(talk.subprocess, "Popen", Decoder)
    with pytest.raises(talk.TalkError, match="已取消"):
        talk._whisper_audio(tmp_path / "long.wav", lambda: "decoding" in events)
    assert events == ["decoding", "killed", "drained"]
