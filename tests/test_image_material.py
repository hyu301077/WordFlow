import json
import wave

import pytest
from PIL import Image

from wordflow import image_material as image
from wordflow.ai import AIError
from wordflow.listen import list_clips


def test_prepared_screenshot_keeps_original_words_for_offline_retry(tmp_path, monkeypatch):
    original = tmp_path / "screenshot.png"
    pack = tmp_path / "pack"
    Image.new("RGB", (120, 60), "white").save(original)
    monkeypatch.setattr(image, "recognize_image", lambda bitmap: "apple 苹果\n银行 bank\n只有中文")
    assert image.prepare_image(original, pack) == "apple\nbank"
    original.unlink()
    assert image.prepare_image(original, pack) == (pack / "ocr.txt").read_text(encoding="utf-8")
    Image.new("RGB", (120, 60), "white").save(original)
    monkeypatch.setattr(image, "recognize_image", lambda bitmap: "中文")
    with pytest.raises(ValueError, match="未识别到英文"):
        image.prepare_image(original, tmp_path / "empty")


def test_ocr_resizes_wide_captures_and_tiles_long_captures(tmp_path, monkeypatch):
    observed = []

    def inspect(bitmap):
        observed.append((bitmap.size, bitmap.getpixel((0, 0))))
        return "book"

    monkeypatch.setattr(image, "recognize_image", inspect)
    wide = tmp_path / "wide.png"
    Image.new("RGBA", (6000, 100), (0, 0, 0, 0)).save(wide)
    image.prepare_image(wide, tmp_path / "wide")
    assert observed == [((3000, 50), (255, 255, 255))]
    tall = tmp_path / "tall.png"
    Image.new("RGB", (80, 7000), "white").save(tall)
    assert image.prepare_image(tall, tmp_path / "tall") == "book\nbook\nbook"
    assert [size for size, color in observed[1:]] == [(80, 3000), (80, 3000), (80, 1000)]


class Model:
    def __init__(self, fail=False, omit=None):
        self.fail = fail
        self.omit = omit
        self.requests = []

    def complete(self, system, prompt):
        words = json.loads(prompt)
        self.requests.append(words)
        if self.fail:
            raise AIError("模型不可用")
        return json.dumps([
            {"target": word, "text": f"I like the {word}.", "translation": "我喜欢它。"}
            for word in words["目标词"] if word != self.omit
        ])


@pytest.fixture
def speech(tmp_path, monkeypatch):
    class TestSpeech:
        spoken = []
        closed = 0
        fail = False

        def configure(self, *args):
            pass

        def synthesize(self, text):
            type(self).spoken.append(text)
            if self.fail:
                return None, "缺少英语语音"
            wav = tmp_path / "tts.wav"
            with wave.open(str(wav), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(b"\0\0" * 8000)
            return wav, ""

        def close(self):
            type(self).closed += 1

    monkeypatch.setattr(image, "SpeechService", TestSpeech)
    return TestSpeech


def test_missing_audio_can_resume_offline_and_preserve_completed_rows(tmp_path, speech):
    targets = ["apple", "bank"]
    examples = tmp_path / "sentences_by_sentence" / "index.json"
    assert "待生成" in image.enrich_image(tmp_path, targets, ["like"], None, {})
    model = Model()
    speech.fail = True
    assert "语音待补" in image.enrich_image(tmp_path, targets, ["like"], model, {})
    rows = json.loads(examples.read_text(encoding="utf-8"))
    assert [(row["id"], row["target"]) for row in rows] == [("001", "apple"), ("002", "bank")]
    assert all(row["text"] and row["translation"] and row["duration"] is None for row in rows)
    assert model.requests == [{"目标词": targets, "熟词": ["like"]}]
    speech.fail = False
    assert image.enrich_image(tmp_path, targets, [], None, {}) == ""
    clips = list_clips(examples.parent)
    assert [clip["name"] for clip in clips] == ["001.mp3", "002.mp3"]
    assert all(clip["duration"] == pytest.approx(0.5) and clip["path"].stat().st_size for clip in clips)
    assert not (tmp_path / "tts.wav").exists()
    count = len(speech.spoken)
    assert image.enrich_image(tmp_path, targets[::-1], [], model, {}) == ""
    assert len(speech.spoken) == count and len(model.requests) == 1
    assert speech.closed == 2


def test_partial_generation_retries_only_missing_word_and_cancellation_keeps_text(tmp_path, speech):
    targets = ["apple", "bank"]
    assert "待补" in image.enrich_image(tmp_path, targets, [], Model(omit="apple"), {})
    failed = Model(fail=True)
    assert "模型不可用" in image.enrich_image(tmp_path, targets, [], failed, {})
    assert failed.requests[0]["目标词"] == ["apple"]
    completed = Model()
    image.enrich_image(tmp_path, targets, [], completed, {})
    assert completed.requests[0]["目标词"] == ["apple"]
    live = []
    with pytest.raises(InterruptedError, match="取消"):
        image.enrich_image(tmp_path, ["apple", "new"], [], completed, {},
                           progress=live.append, cancelled=lambda: bool(live))
    rows = json.loads((tmp_path / "sentences_by_sentence" / "index.json").read_text(encoding="utf-8"))
    assert [row["target"] for row in rows] == ["bank", "apple", "new"]
    assert rows[0]["id"] == "001" and rows[-1]["duration"] is None
