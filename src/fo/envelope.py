"""Error envelope and JSON encoding shared by the CLI and fo serve.

Kept free of Typer so the server can import it without building the CLI.
"""

import json
import sqlite3
import subprocess

from fo.errors import OfficeError

# Failures that may carry paths, input snippets, provider bodies, or credentials in their text.
SAFE_FAILURES = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    ArithmeticError,
    sqlite3.Error,
    subprocess.TimeoutExpired,
)
FAILED = {
    "reason": "operation_failed",
    "message": "Operation failed; check configuration and file permissions.",
}


def encode(value) -> str:
    """JSON with decimals and dates as strings, the numeric contract of every command."""
    return json.dumps(value, ensure_ascii=False, default=str)


def failure(exc: BaseException) -> dict:
    """The public envelope for a failed operation; never exception text or paths."""
    if isinstance(exc, OfficeError):
        return {"reason": exc.reason, "message": exc.message}
    return dict(FAILED)
