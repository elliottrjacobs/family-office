import re


def untrusted_text(value):
    if value is None:
        return None
    text = re.sub(r"https?://\S+@\S+", "[credential URL omitted]", str(value))
    return re.sub(r"\b\d{8,}\b", lambda match: "…" + match[0][-4:], text)
