"""跨模块共用的状态和界面文案。"""

STATUS_UNTESTED = "untested"
STATUS_PENDING = "pending"
STATUS_LEARNING = "learning"
STATUS_REVIEWING = "reviewing"
STATUS_MASTERED = "mastered"

NEW_WORD_STATUSES = (STATUS_LEARNING, STATUS_REVIEWING)

STATUS_LABELS = {
    STATUS_UNTESTED: "未测试",
    STATUS_PENDING: "待确认",
    STATUS_LEARNING: "学习中",
    STATUS_REVIEWING: "复习中",
    STATUS_MASTERED: "已掌握",
}

RATING_AGAIN = "again"
RATING_HARD = "hard"
RATING_GOOD = "good"
RATING_EASY = "easy"
RATING_MASTERED = "mastered"
RATING_SKIP = "skip"
