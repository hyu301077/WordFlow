"""应用运行时用到的对象。"""

from __future__ import annotations

from pathlib import Path

from wordflow.dictionary import Dictionary
from wordflow.paths import backup_dir, database_path, find_dictionary, user_data_dir
from wordflow.settings import Settings
from wordflow.store import Store
from wordflow.tts import SpeechService


class AppContext:
    def __init__(self, db_path: Path | None = None, dict_path: Path | None = None):
        self.data_dir = user_data_dir()
        self.db_path = Path(db_path) if db_path else database_path()
        self.backup_path = backup_dir()
        self.dict_path = Path(dict_path) if dict_path else find_dictionary()
        self.store = Store(self.db_path)
        self.dictionary = Dictionary(self.dict_path)
        self.settings = Settings(self.store)
        self.speech = SpeechService()
        self.apply_speech()

    def apply_speech(self) -> None:
        self.speech.configure(
            self.settings.get("voice_pref", "en-US"),
            self.settings.integer("speech_rate", 0),
            self.settings.integer("speech_volume", 80),
        )

    def reopen_store(self) -> None:
        try:
            self.store.close()
        except Exception:
            pass
        self.store = Store(self.db_path)
        self.settings = Settings(self.store)

    def close(self) -> None:
        self.speech.close()
        try:
            self.store.close()
        except Exception:
            pass
        try:
            self.dictionary.close()
        except Exception:
            pass
