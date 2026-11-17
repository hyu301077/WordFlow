"""用户设置。缺省值可离线使用，不依赖网络。"""

from __future__ import annotations

from wordflow.extract import ExtractOptions
from wordflow.paths import stopwords_path

DEFAULTS: dict[str, str] = {
    "theme": "light",
    "daily_new_limit": "20",
    "auto_speak": "1",
    "voice_pref": "en-US",
    "speech_rate": "0",
    "speech_volume": "80",
    "filter_stopwords": "1",
    "filter_proper": "1",
    "filter_acronyms": "1",
    "scan_mode": "project_output",
    "show_reading_marks": "1",
    "learn_mode": "card",
    "review_mode": "card",
    "placement_count": "20",
    "review_limit": "50",
    "reminder": "1",
    "active_deck_id": "0",
    "ocr_max_pages": "40",
    "ai_enabled": "0",
    "ai_consent": "0",
    "ai_base_url": "",
    "ai_model": "",
    "ai_api_key": "",
    "listen_folder": "",
    "listen_device": "",
    "listen_rate": "1",
    "listen_loop": "0",
    "placement_sentence_rate": "1",
    "talk_model": "small",
    "desired_retention": "0.90",
    "leech_threshold": "8",
}


class Settings:
    def __init__(self, store):
        self.store = store
        self.cache = dict(DEFAULTS)
        self.cache.update(store.all_settings())

    def get(self, key: str, default: str | None = None) -> str:
        if key in self.cache:
            return self.cache[key]
        if default is not None:
            return default
        return DEFAULTS.get(key, "")

    def set(self, key: str, value) -> None:
        text = str(value)
        self.cache[key] = text
        self.store.set_setting(key, text)

    def flag(self, key: str) -> bool:
        return self.get(key, "0").strip().lower() in {"1", "true", "yes", "on"}

    def real(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def integer(self, key: str, default: int = 0) -> int:
        try:
            return int(float(self.get(key, str(default))))
        except (TypeError, ValueError):
            return default

    def extract_options(self) -> ExtractOptions:
        return ExtractOptions(
            filter_stopwords=self.flag("filter_stopwords"),
            filter_proper=self.flag("filter_proper"),
            filter_acronyms=self.flag("filter_acronyms"),
            stopwords_path=stopwords_path(),
        )
