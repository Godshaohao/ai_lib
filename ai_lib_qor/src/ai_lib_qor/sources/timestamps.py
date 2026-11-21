"""UTC interchange for instants; supplier version dates remain date-only values."""
from datetime import datetime, timezone


def instant(value):
    if isinstance(value,str):value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('时间必须带有时区')
    return value.astimezone(timezone.utc)


def utc_text(value=None):
    value=instant(value if value is not None else datetime.now(timezone.utc))
    return value.isoformat(timespec='seconds').replace('+00:00','Z')
