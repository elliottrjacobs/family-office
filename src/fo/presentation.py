"""Compact command output; full mode preserves provider payloads and every row."""

import json

from rich.console import Console
from rich.table import Table


def summary(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    omitted = {}
    for key, item in value.items():
        if isinstance(item, list) and len(item) > 20:
            result[key] = item[:20]
            omitted[key] = len(item) - 20
    data = result.get("data")
    if isinstance(data, dict) and "normalized" in data:
        result["data"] = {
            k: data[k] for k in ("Symbol", "normalized", "source_period", "metrics") if k in data
        }
    if omitted:
        result["omitted_rows"] = omitted
    return result


def human(value):
    console = Console(highlight=False, markup=False)

    def cell(item):
        return (
            "unknown"
            if item is None
            else json.dumps(item, default=str, ensure_ascii=False)
            if isinstance(item, (dict, list))
            else str(item)
        )

    rows = value if isinstance(value, list) else [value]
    if rows and all(isinstance(row, dict) for row in rows):
        # One record is easiest to scan vertically; repeated records share columns.
        if len(rows) == 1:
            table = Table("Field", "Value")
            for key, item in rows[0].items():
                table.add_row(str(key), cell(item))
        else:
            keys = list(dict.fromkeys(k for row in rows for k in row))
            table = Table(*keys)
            for row in rows:
                table.add_row(*(cell(row.get(k)) for k in keys))
        console.print(table)
    else:
        console.print(cell(value))
