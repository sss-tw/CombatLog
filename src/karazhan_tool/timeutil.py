"""日志时钟与 Unix 毫秒的转换。时区来自当周配置，不依赖本机时区。"""

from __future__ import annotations

import datetime as dt
import re

CLOCK_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$")
ZONE_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def parse_timezone(value: str) -> dt.timezone:
    match = ZONE_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"时区格式必须是 +08:00 这种写法：{value}")
    sign = 1 if match.group(1) == "+" else -1
    hours = int(match.group(2))
    minutes = int(match.group(3))
    return dt.timezone(dt.timedelta(hours=sign * hours, minutes=sign * minutes))


def parse_clock(value: str) -> float:
    """把 HH:MM:SS.mmm 转成从当地零点起的秒数。"""
    match = CLOCK_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"无法解析日志时间：{value}")
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3))
    millis = int(match.group(4))
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError(f"日志时间超出范围：{value}")
    return hour * 3600 + minute * 60 + second + millis / 1000


def clock_to_epoch_ms(date_text: str, clock: str, timezone: str) -> int:
    parse_clock(clock)
    day = dt.date.fromisoformat(date_text)
    hour_text, minute_text, rest = clock.split(":")
    second_text, millis_text = rest.split(".")
    moment = dt.datetime(
        day.year,
        day.month,
        day.day,
        int(hour_text),
        int(minute_text),
        int(second_text),
        int(millis_text) * 1000,
        tzinfo=parse_timezone(timezone),
    )
    return int(moment.timestamp() * 1000)


def epoch_ms_to_local(epoch_ms: int, timezone: str) -> tuple[str, str]:
    moment = dt.datetime.fromtimestamp(epoch_ms / 1000, tz=parse_timezone(timezone))
    clock = (
        f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}."
        f"{moment.microsecond // 1000:03d}"
    )
    return moment.date().isoformat(), clock


def log_month_day(date_text: str) -> str:
    """魔兽战斗日志的日期前缀不补零，例如 11/18。"""
    day = dt.date.fromisoformat(date_text)
    return f"{day.month}/{day.day}"
