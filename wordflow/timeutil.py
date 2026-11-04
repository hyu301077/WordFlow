"""本地时间。复习时间和学习日都按用户本机时区计算。"""

from __future__ import annotations

from datetime import datetime, timedelta


def now_local() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def today_str() -> str:
    return now_local().date().isoformat()


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone().replace(microsecond=0).isoformat(timespec="seconds")


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def add_days(origin: datetime, days: float) -> datetime:
    return (origin + timedelta(days=days)).replace(microsecond=0)
