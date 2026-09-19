import re
from datetime import UTC, datetime


def untrusted_text(value):
    if value is None:
        return None
    text = re.sub(r"https?://\S+@\S+", "[credential URL omitted]", str(value))
    return re.sub(r"\b\d{8,}\b", lambda match: "…" + match[0][-4:], text)


def local_date(value, timezone=UTC):
    """Office-local calendar date for a provider epoch or ISO timestamp; date-only text passes."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC).astimezone(timezone).date().isoformat()
    text = str(value)
    if len(text) <= 10:
        return text
    stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        return stamp.date().isoformat()
    return stamp.astimezone(timezone).date().isoformat()
