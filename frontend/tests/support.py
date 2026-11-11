"""测试用的小型 ECDICT 结构。释义都是明确的测试数据，不进入正式词典。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ENTRIES = [
    ("apple", "ˈæpl", "a round fruit", "n. 苹果；苹果树", "n", 1, 200, "s:apples"),
    ("apples", "", "", "0:apple/1:s", "", 0, 0, "0:apple/1:s"),
    ("abandon", "əˈbændən", "to leave completely", "v. 放弃；抛弃\nn. 放任", "v", 1, 800, "d:abandoned/i:abandoning"),
    ("run", "rʌn", "to move quickly", "v. 奔跑；经营\nn. 奔跑", "v", 1, 100, "i:running/p:ran"),
    ("running", "ˈrʌnɪŋ", "", "0:run/1:i", "", 0, 0, "0:run/1:i"),
    ("record", "ˈrekɔːd", "a written account", "n. 记录；档案\nv. 录制；记载", "n", 1, 500, "s:records"),
    ("book", "bʊk", "a set of pages", "n. 书籍；著作\nv. 预订", "n", 1, 150, "s:books"),
    ("bank", "bæŋk", "a financial institution", "n. 银行；河岸", "n", 1, 400, "s:banks"),
    ("accept", "əkˈsept", "to receive willingly", "v. 接受；同意", "v", 1, 600, ""),
    ("except", "ɪkˈsept", "not including", "prep. 除了；除外", "prep", 1, 700, ""),
    ("affect", "əˈfekt", "to influence", "v. 影响；感动", "v", 1, 650, ""),
    ("effect", "ɪˈfekt", "a result", "n. 效果；影响", "n", 1, 650, ""),
    ("adopt", "əˈdɒpt", "to take as one's own", "v. 采用；收养", "v", 1, 900, ""),
    ("adapt", "əˈdæpt", "to adjust", "v. 适应；改编", "v", 1, 900, ""),
    ("study", "ˈstʌdi", "learning", "n. 学习；研究\nv. 学习", "n", 1, 300, "i:studying/3:studies"),
    ("studies", "", "", "0:study/1:3", "", 0, 0, "0:study/1:3"),
    ("happy", "ˈhæpi", "feeling pleasure", "a. 高兴的；幸福的", "a", 1, 250, ""),
    ("computer", "kəmˈpjuːtə", "an electronic machine", "n. 计算机；电脑", "n", 1, 350, ""),
    ("language", "ˈlæŋɡwɪdʒ", "a system of words", "n. 语言", "n", 1, 320, ""),
    ("science", "ˈsaɪəns", "systematic knowledge", "n. 科学", "n", 1, 280, ""),
    ("history", "ˈhɪstri", "past events", "n. 历史", "n", 1, 310, ""),
    ("music", "ˈmjuːzɪk", "sound organized in time", "n. 音乐", "n", 1, 330, ""),
    ("water", "ˈwɔːtə", "a liquid", "n. 清水；水域", "n", 1, 180, ""),
    ("develop", "dɪˈveləp", "to grow", "v. 发展；开发", "v", 1, 420, ""),
    ("provide", "prəˈvaɪd", "to supply", "v. 提供；供应", "v", 1, 480, ""),
    ("idea", "aɪˈdɪə", "a thought", "n. 想法；主意", "n", 1, 360, ""),
    ("important", "ɪmˈpɔːtnt", "having value", "a. 重要的", "a", 1, 220, ""),
    ("system", "ˈsɪstəm", "a set of parts", "n. 系统；体系", "n", 1, 390, ""),
    ("leaf", "liːf", "part of a plant", "n. 叶子", "n", 1, 1400, ""),
    ("leave", "liːv", "to go away", "v. 离开；留下", "v", 1, 200, ""),
    ("make", "meɪk", "to create", "v. 制作；使得", "v", 1, 80, ""),
    ("stop", "stɒp", "to end", "v. 停止；阻止", "v", 1, 90, ""),
    ("the", "ðə", "definite article", "art. 这；那", "art", 1, 1, ""),
]


def write_dictionary(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE stardict (
            id INTEGER PRIMARY KEY,
            word TEXT NOT NULL UNIQUE,
            phonetic TEXT,
            definition TEXT,
            translation TEXT,
            pos TEXT,
            collins INTEGER,
            oxford INTEGER,
            frq INTEGER,
            exchange TEXT
        )
        """
    )
    for index, (word, phonetic, definition, translation, pos, oxford, frq, exchange) in enumerate(ENTRIES, start=1):
        connection.execute(
            """
            INSERT INTO stardict(id, word, phonetic, definition, translation, pos, collins, oxford, frq, exchange)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (index, word, phonetic, definition, translation, pos, oxford, frq, exchange),
        )
    connection.commit()
    connection.close()
