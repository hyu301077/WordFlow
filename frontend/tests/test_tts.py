from wordflow.tts import SpeechService


def test_missing_engine_explains_instead_of_crashing():
    service = SpeechService.__new__(SpeechService)
    service.available = False
    service.voices = []
    service.error = ""
    service._voice = None
    ok, message = service.speak("apple")
    assert ok is False
    assert "语音" in message


def test_missing_english_voice_is_explicit():
    service = SpeechService.__new__(SpeechService)
    service.available = True
    service.voices = [{"language": "zh-CN", "name": "Hui", "token": object()}]
    service.error = ""
    service._voice = object()
    service.pref = "en-US"
    service.rate = 0
    service.volume = 80
    ok, message = service.speak("apple")
    assert ok is False
    assert "英语" in message
