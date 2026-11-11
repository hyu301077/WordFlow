import array
import json
import os
from pathlib import Path

from PySide6.QtMultimedia import QAudioFormat

from wordflow.listen import list_clips
from wordflow.playback import render_pcm

EXPERIMENT = Path(r"D:\github\英语学习\talks\运动改变大脑\sentences_by_sentence")


def test_list_clips_sorts_mp3s_and_reads_index(tmp_path: Path):
    folder = tmp_path / "clips"
    nested = folder / "part"
    nested.mkdir(parents=True)
    (folder / "010.mp3").write_bytes(b"not-audio")
    (folder / "002.mp3").write_bytes(b"not-audio")
    (nested / "001.mp3").write_bytes(b"not-audio")
    (folder / "note.txt").write_text("skip", encoding="utf-8")
    (folder / "index.json").write_text(
        json.dumps(
            [
                {"id": "002", "text": "Second sentence.", "duration": 3.5},
                {"id": "010", "text": "Tenth.", "duration": 1},
            ]
        ),
        encoding="utf-8",
    )
    rows = list_clips(folder)
    assert [row["name"] for row in rows] == ["002.mp3", "010.mp3", "part/001.mp3"]
    assert rows[0]["text"] == "Second sentence."
    assert rows[0]["duration"] == 3.5
    assert rows[2]["text"] == ""


def test_listen_page_lists_folder_and_keeps_rate(tmp_path: Path):
    os.environ["WORDFLOW_DATA"] = str(tmp_path / "data")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    from wordflow.context import AppContext
    from wordflow.ui.listen import ListenPage
    from tests.support import write_dictionary

    QApplication.instance() or QApplication([])
    dictionary = tmp_path / "dict.db"
    write_dictionary(dictionary)
    folder = tmp_path / "clips"
    folder.mkdir()
    (folder / "001.mp3").write_bytes(b"not-audio")
    (folder / "002.mp3").write_bytes(b"not-audio")
    ctx = AppContext(db_path=tmp_path / "app.db", dict_path=dictionary)
    page = ListenPage(ctx, None)
    page.scan(folder)
    assert page.model.rowCount() == 2
    assert "2 个 MP3" in page.status.text()
    page._set_rate(0.75)
    assert page.rate == 0.75
    assert abs(page.player.rate - 0.75) < 0.001
    page._set_rate(2)
    assert abs(page.player.rate - 2) < 0.001
    sentence = "What if I told you there was something that you can do right now?"
    (folder / "index.json").write_text(
        json.dumps([{"id": "001", "text": sentence, "duration": 2.5}], ensure_ascii=False),
        encoding="utf-8",
    )
    page.scan(folder)
    page.play_row(0)
    assert page.sentence.text() == sentence
    assert page.model.data(page.model.index(0, 1)) == sentence
    page.loop.setChecked(True)
    assert page.loop.isChecked()
    assert not page.auto_next.isChecked()
    assert ctx.settings.get("listen_loop") == "1"
    calls = []
    page.player.replay = lambda: calls.append("replay") or True
    page._finished()
    assert calls == ["replay"]
    assert page.current == 0
    page.loop.setChecked(False)
    page.auto_next.setChecked(True)
    page._finished()
    assert page.current == 1
    ctx.close()


def _pitch_hz(samples, sample_rate: int) -> float:
    crossings = 0
    for index in range(1, len(samples)):
        previous = samples[index - 1]
        current = samples[index]
        if previous <= 0 < current or previous >= 0 > current:
            crossings += 1
    duration = len(samples) / sample_rate
    return (crossings / 2) / duration if duration else 0.0


def test_slow_speed_keeps_pitch_and_gets_longer():
    import math

    from wordflow.playback import stretch_keep_pitch

    sample_rate = 16000
    seconds = 1.0
    count = int(sample_rate * seconds)
    tone = [math.sin(2 * math.pi * 440 * index / sample_rate) for index in range(count)]
    slow = stretch_keep_pitch(tone, 0.5, sample_rate)
    slower = stretch_keep_pitch(tone, 0.75, sample_rate)
    assert len(slow) > count * 1.7
    assert count * 1.15 < len(slower) < count * 1.5
    margin = sample_rate // 5
    slow_hz = _pitch_hz(slow[margin:-margin], sample_rate)
    slower_hz = _pitch_hz(slower[margin:-margin], sample_rate)
    assert 420 < slow_hz < 460
    assert 420 < slower_hz < 460


def test_render_pcm_follows_speed_and_stays_in_range():
    samples = array.array("f", [0.0, 1.0, 0.0, -1.0, 0.0])
    pcm, cursor, ended = render_pcm(samples, 0.0, 4, 0.5, 2, QAudioFormat.SampleFormat.Float)
    assert not ended
    assert cursor == 2.0
    assert len(pcm) == 4 * 2 * 4
    fast, fast_cursor, fast_ended = render_pcm(samples, 0.0, 4, 2.0, 2, QAudioFormat.SampleFormat.Float)
    assert fast_cursor == 8.0 or fast_ended
    assert len(fast) < len(pcm)
    assert fast_ended


def test_clip_player_reaches_active_device(tmp_path: Path):
    if not EXPERIMENT.is_dir():
        return
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QTimer
    from PySide6.QtMultimedia import QMediaDevices, QtAudio
    from PySide6.QtWidgets import QApplication

    from wordflow.playback import ClipPlayer

    app = QApplication.instance() or QApplication([])
    if not QMediaDevices.audioOutputs():
        return
    player = ClipPlayer()
    seen = {}

    player.failed.connect(lambda message: seen.setdefault("failed", message))
    player.play_file(str(EXPERIMENT / "001.mp3"))
    attempts = {"count": 0}

    def finish():
        attempts["count"] += 1
        started = player.sink is not None and player.sink.processedUSecs() > 0
        if not started and "failed" not in seen and attempts["count"] < 25:
            QTimer.singleShot(200, finish)
            return
        sink = player.sink
        seen["state"] = sink.state() if sink else None
        seen["processed"] = sink.processedUSecs() if sink else 0
        seen["error"] = str(sink.error()) if sink else ""
        seen["rate"] = player.out_format.sampleRate() if player.out_format else 0
        player.stop()
        app.quit()

    QTimer.singleShot(200, finish)
    app.exec()
    assert "failed" not in seen
    assert seen["state"] == QtAudio.State.ActiveState
    assert seen["processed"] > 0
    assert seen["rate"] == QMediaDevices.defaultAudioOutput().preferredFormat().sampleRate()


def test_experiment_sentence_folder_lists_every_clip():
    if not EXPERIMENT.is_dir():
        return
    rows = list_clips(EXPERIMENT)
    assert len(rows) == 73
    assert rows[0]["name"] == "001.mp3"
    assert rows[-1]["name"] == "073.mp3"
    assert rows[0]["text"].startswith("What if I told you")
    assert all(row["name"].lower().endswith(".mp3") for row in rows)
