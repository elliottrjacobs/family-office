import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


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


# Elements whose content never reaches the markdown: code, styling, embedded documents,
# form controls, and the document head.
DROPPED = {
    "script",
    "style",
    "noscript",
    "template",
    "head",
    "svg",
    "math",
    "iframe",
    "frame",
    "frameset",
    "object",
    "embed",
    "canvas",
    "audio",
    "video",
    "select",
    "option",
    "button",
    "textarea",
    "input",
    "dialog",
}
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
BLOCKS = {
    "p",
    "div",
    "section",
    "article",
    "header",
    "footer",
    "main",
    "aside",
    "nav",
    "blockquote",
    "figure",
    "figcaption",
    "dl",
    "dt",
    "dd",
    "address",
    "details",
    "summary",
    "body",
    "html",
}
HEADING = re.compile(r"h[1-6]")
HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?![.\d])")
HIDDEN_CLASSES = {"hidden", "sr-only", "visually-hidden", "d-none", "screen-reader-text"}


def hidden(attrs):
    values = {key.lower(): (value or "") for key, value in attrs}
    return (
        "hidden" in values
        or values.get("aria-hidden", "").lower() == "true"
        or bool(HIDDEN_STYLE.search(values.get("style", "").lower()))
        or values.get("type", "").lower() == "hidden"
        or bool(HIDDEN_CLASSES & set(values.get("class", "").lower().split()))
    )


class _Markdown(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.blocks = []
        self.line = []
        self.prefix = ""
        self.skip_tag, self.skip_depth = None, 0
        self.lists = []
        self.links = []
        self.table, self.cell, self.table_depth = None, None, 0
        self.pre = 0

    def target(self):
        return self.cell if self.cell is not None else self.line

    def flush(self):
        text = "".join(self.line)
        text = text.strip("\n") if self.pre else text.strip()
        if text:
            self.blocks.append(self.prefix + text)
        self.line, self.prefix = [], ""

    def handle_starttag(self, tag, attrs):
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        if tag in DROPPED or hidden(attrs):
            if tag not in VOID:
                self.skip_tag, self.skip_depth = tag, 1
            return
        if tag in BLOCKS or tag == "br":
            if self.cell is None:
                self.flush()
            else:
                self.cell.append(" ")
        elif HEADING.fullmatch(tag):
            self.flush()
            self.prefix = "#" * int(tag[1]) + " "
        elif tag in ("ul", "ol"):
            self.flush()
            self.lists.append([tag, 0])
        elif tag == "li":
            self.flush()
            if self.lists:
                self.lists[-1][1] += 1
                kind, count = self.lists[-1]
                bullet = f"{count}. " if kind == "ol" else "- "
                self.prefix = "  " * (len(self.lists) - 1) + bullet
            else:
                self.prefix = "- "
        elif tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            url = urljoin(self.base, href) if self.base else href
            keep = url if href and urlsplit(url).scheme in ("http", "https") else None
            target = self.target()
            self.links.append((keep, target, len(target)))
        elif tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.flush()
                self.table = []
        elif tag == "tr" and self.table_depth == 1:
            self.table.append([])
        elif tag in ("td", "th") and self.table_depth == 1:
            if not self.table:
                self.table.append([])
            self.cell = []
        elif tag == "pre":
            self.flush()
            self.pre += 1
            self.line.append("```\n")
        elif tag == "code" and not self.pre:
            self.target().append("`")
        elif tag == "hr":
            self.flush()
            self.blocks.append("---")

    def handle_endtag(self, tag):
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return
        if tag in BLOCKS or HEADING.fullmatch(tag) or tag == "li":
            if self.cell is None:
                self.flush()
        elif tag in ("ul", "ol"):
            self.flush()
            if self.lists:
                self.lists.pop()
        elif tag == "a" and self.links:
            url, target, start = self.links.pop()
            text = "".join(target[start:]).strip()
            del target[start:]
            if text:
                target.append(f"[{text}]({url})" if url else text)
        elif tag in ("td", "th") and self.cell is not None and self.table_depth == 1:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|")
            self.table[-1].append(text)
            self.cell = None
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0:
                self.emit_table()
        elif tag == "pre" and self.pre:
            self.line.append("\n```")
            self.flush()
            self.pre -= 1
        elif tag == "code" and not self.pre:
            self.target().append("`")

    def handle_data(self, data):
        if self.skip_tag:
            return
        if self.pre:
            self.line.append(data)
            return
        self.target().append(re.sub(r"\s+", " ", data))

    def emit_table(self):
        if self.cell is not None and self.table:
            self.handle_endtag("td")
        rows = [row for row in self.table or [] if any(row)]
        self.table, self.cell = None, None
        if not rows:
            return
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
        self.blocks.append("\n".join(lines))

    def close(self):
        super().close()
        if self.table is not None:
            self.emit_table()
        self.flush()


def html_to_markdown(html, base=None):
    """Plain markdown from HTML: headings, paragraphs, lists, links, and tables only.

    Scripts, styles, hidden elements, form controls, embedded documents, comments, and
    every attribute except a link's http(s) target are dropped, so text a page hides from
    readers does not reach an advisor.
    """
    parser = _Markdown(base)
    parser.feed(html)
    parser.close()
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(parser.blocks)).strip()
