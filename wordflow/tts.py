"""Windows 系统语音。没有英语语音时给出原因，不让程序崩溃。"""

from __future__ import annotations

_ENGLISH = {
    0x0409: "en-US",
    0x0809: "en-GB",
    0x0C09: "en-AU",
    0x1009: "en-CA",
    0x1409: "en-NZ",
    0x1809: "en-IE",
    0x4809: "en-IN",
}
_NO_ENGINE = "无法初始化 Windows 语音引擎。"
_NO_ENGLISH = "未找到英语语音。请打开 Windows「设置 → 时间和语言 → 语音」，添加英语（美国或英国）语音包后再试。"


class SpeechService:
    def __init__(self):
        self.available = False
        self.voices: list[dict] = []
        self.error = ""
        self.pref = "en-US"
        self.rate = 0
        self.volume = 80
        self._voice = None
        try:
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            import win32com.client

            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            self.available = True
            self._load_voices()
            if not self.english_voices():
                self.error = _NO_ENGLISH
        except Exception as exc:
            self.available = False
            self.error = f"{_NO_ENGINE}{exc}"

    def configure(self, pref: str, rate: int, volume: int) -> None:
        self.pref = pref or "en-US"
        self.rate = max(-10, min(10, int(rate)))
        self.volume = max(0, min(100, int(volume)))

    def english_voices(self) -> list[dict]:
        return [voice for voice in self.voices if str(voice.get("language", "")).startswith("en")]

    def speak(self, text: str) -> tuple[bool, str]:
        content = (text or "").strip()
        if not content:
            return False, "没有可朗读的内容"
        content = content[:500]
        if not self.available or self._voice is None:
            return False, self.error or _NO_ENGINE
        if not self.english_voices():
            return False, self.error or _NO_ENGLISH
        try:
            self._apply_voice()
            # 1 = 异步，2 = 先停掉上一句，避免连续点击叠在一起。
            self._voice.Speak(content, 1 | 2)
            return True, ""
        except Exception as exc:
            return False, f"朗读失败：{exc}"

    def _load_voices(self) -> None:
        tokens = self._voice.GetVoices()
        for index in range(tokens.Count):
            token = tokens.Item(index)
            try:
                description = str(token.GetDescription())
            except Exception:
                description = f"Voice {index}"
            language = ""
            try:
                language = _language_name(str(token.GetAttribute("Language")))
            except Exception:
                language = ""
            if not language and "english" in description.lower():
                lowered = description.lower()
                if "united kingdom" in lowered or "british" in lowered:
                    language = "en-GB"
                else:
                    language = "en-US"
            self.voices.append({"id": str(getattr(token, "Id", index)), "name": description, "language": language, "token": token})

    def _apply_voice(self) -> None:
        chosen = None
        english = self.english_voices()
        for voice in english:
            if voice["language"].lower().startswith(self.pref.lower()):
                chosen = voice
                break
        if chosen is None and english:
            chosen = english[0]
        if chosen is not None:
            self._voice.Voice = chosen["token"]
        self._voice.Rate = self.rate
        self._voice.Volume = self.volume


def _language_name(value: str) -> str:
    try:
        number = int(value, 16)
    except (TypeError, ValueError):
        return ""
    if number & 0x3FF == 0x09:
        return _ENGLISH.get(number, "en")
    if number & 0x3FF == 0x04:
        return "zh"
    return ""
