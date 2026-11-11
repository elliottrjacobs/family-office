import copy
import json
import math
import os
import re
import sys
import tomllib
import uuid
from pathlib import Path
from zoneinfo import available_timezones

from fo.errors import OfficeError
from fo.office import contained

CREDENTIAL_READ_DENIES = (
    "Read(~/Library/Application Support/FamilyOffice/credentials/**)",
    "Read(~/.local/share/family-office/credentials/**)",
)
MANAGED_CREDENTIAL_FILES = {
    "keys.toml",
    "alphavantage.json",
    "fred.json",
    "exa.json",
    "firecrawl.json",
    "gemini.json",
    "schwab-token.json",
    "devices.json",
}


def credentials_read_denied(root: Path, *, fix: bool = False) -> bool:
    """Check or add credential read denies in an existing Claude settings file."""
    from fo.office import write_json

    path = contained(root, ".claude/settings.json")
    if not path.exists():
        return True
    settings = load_json(path)
    permissions = settings.get("permissions", {}) if isinstance(settings, dict) else None
    deny = permissions.get("deny", []) if isinstance(permissions, dict) else None
    if not isinstance(deny, list) or not all(isinstance(rule, str) for rule in deny):
        raise OfficeError(
            "invalid_config", "The office .claude/settings.json permissions are malformed."
        )
    missing = [rule for rule in CREDENTIAL_READ_DENIES if rule not in deny]
    if missing and fix:
        settings.setdefault("permissions", {}).setdefault("deny", []).extend(missing)
        write_json(path, settings, path.stat().st_mode & 0o777)
    return not missing or fix


def read_config(root: Path) -> dict:
    try:
        return tomllib.loads(contained(root, "office.toml").read_text())
    except (OSError, ValueError) as exc:
        raise OfficeError("invalid_config", "office.toml is unreadable or invalid TOML.") from exc


def credentials_dir(root: Path) -> Path:
    """Resolve credentials without writing or migrating anything."""
    office_id = read_config(root).get("office", {}).get("id")
    if office_id is None:
        raise OfficeError(
            "credentials_not_migrated",
            "Run fo doctor --fix (or a credential-writing command) once to migrate credentials.",
        )
    if not isinstance(office_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", office_id):
        raise OfficeError("invalid_config", "office.id must be a non-empty path-safe id.")
    if os.environ.get("FO_CREDENTIALS_HOME"):
        base = Path(os.environ["FO_CREDENTIALS_HOME"]).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support/FamilyOffice/credentials"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
        base = base / "family-office/credentials"
    base = base.absolute()
    if base.resolve().is_relative_to(root.resolve()):
        raise OfficeError("unsafe_path", "Credentials must live outside the office folder.")
    directory = base / office_id
    for path in (base, directory, root / "secrets"):
        if path.is_symlink():
            raise OfficeError("unsafe_path", "Credentials directories must not be symlinks.")
    if directory.exists() and any(path.is_symlink() for path in directory.iterdir()):
        raise OfficeError("unsafe_path", "Credential files must not be symlinks.")
    return directory


def ensure_credentials(root: Path) -> Path:
    """Create the identity and local directory, then migrate legacy secrets."""
    from fo.lock import office_lock
    from fo.office import atomic_write

    # Check the agent read-deny first, so a bad settings file stops migration before the id.
    try:
        credentials_read_denied(root, fix=True)
    except OSError as exc:
        raise OfficeError(
            "invalid_config", "The office .claude/settings.json could not be updated."
        ) from exc
    if read_config(root).get("office", {}).get("id") is None:
        with office_lock(root, wait=LOCK_WAIT):
            if read_config(root).get("office", {}).get("id") is None:
                _write_config(root, "office.id", uuid.uuid4().hex)
    directory = credentials_dir(root)
    try:
        directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        legacy = root / "secrets"
        if legacy.is_dir():
            for source in legacy.iterdir():
                if (
                    source.name not in MANAGED_CREDENTIAL_FILES
                    or source.is_symlink()
                    or not source.is_file()
                ):
                    continue
                destination = directory / source.name
                if destination.is_symlink():
                    continue
                try:
                    if not destination.exists():
                        atomic_write(destination, source.read_bytes(), 0o600)
                    if destination.read_bytes() == source.read_bytes():
                        destination.chmod(0o600)
                        source.unlink()
                except OSError:
                    continue  # Doctor reports office copies that could not be migrated.
            try:
                legacy.rmdir()
            except OSError:
                pass
        return directory
    except OSError as exc:
        raise OfficeError(
            "credentials_unavailable", "The local credentials folder is unavailable."
        ) from exc


def read_secrets(root: Path) -> dict:
    path = credentials_dir(root) / "keys.toml"
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OfficeError(
            "invalid_secrets", "The secrets file is unreadable or invalid TOML."
        ) from exc


def provider_key(root: Path, provider: str) -> str | None:
    """The local <provider>.json API key, falling back to the key fo auth stored."""
    path = credentials_dir(root) / f"{provider}.json"
    if path.exists():
        try:
            key = json.loads(path.read_text()).get("api_key")
        except (OSError, ValueError, AttributeError) as exc:
            raise OfficeError(
                "invalid_secrets", "A provider key file is unreadable or malformed."
            ) from exc
        return key if isinstance(key, str) and key else None
    key = read_secrets(root).get(provider, {}).get("api_key")
    return key if isinstance(key, str) and key else None


def masked(value):
    if isinstance(value, dict):
        return {key: masked(item) for key, item in value.items()}
    if isinstance(value, list):
        return [masked(item) for item in value]
    return "***"


def public_config(root: Path) -> dict:
    """Settings plus which secrets exist, every value masked.

    Local <provider>.json keys show up beside keys.toml entries so clients can
    tell which providers are connected without reading credentials.
    """
    secrets = masked(read_secrets(root))
    for provider in PROVIDERS:
        if (credentials_dir(root) / f"{provider}.json").exists():
            secrets[provider] = {"api_key": "***"}
    return {"settings": read_config(root), "secrets": secrets}


HOSTNAME = re.compile(
    r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
)
INTEGER = re.compile(r"[+-]?\d+")
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _integer(minimum=0, maximum=None, excluded=()):
    def parse(text):
        if not INTEGER.fullmatch(text.strip()):
            return None
        value = int(text)
        if value < minimum or (maximum is not None and value > maximum) or value in excluded:
            return None
        return value

    return parse


def _positive_float(text):
    if not NUMBER.fullmatch(text.strip()):
        return None
    value = float(text)
    return value if math.isfinite(value) and value > 0 else None


def _boolean(text):
    return {"true": True, "false": False}.get(text.strip().lower())


def _choice(*options):
    return lambda text: text.strip() if text.strip() in options else None


def _text(text, limit=200):
    text = text.strip()
    return text if 0 < len(text) <= limit and text.isprintable() else None


def _token(text):
    text = _text(text)
    return text if text and not any(c.isspace() for c in text) else None


def _timezone(text):
    text = text.strip()
    return text if text in available_timezones() else None


def _hostname(text):
    text = text.strip()
    return text if HOSTNAME.fullmatch(text) else None


def _logins(text):
    text = text.strip()
    if text.startswith("["):
        try:
            items = json.loads(text)
        except ValueError:
            return None
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            return None
    else:
        items = [item for item in text.split(",") if item.strip()]
    logins = [_token(item) for item in items]
    return None if None in logins else logins


def _schema():
    from fo.serve import RESERVED_PORTS

    port = " other than " + ", ".join(map(str, sorted(RESERVED_PORTS)))
    schema = {
        "hosts.writer": (_text, "non-empty single-line text"),
        "office.timezone": (_timezone, "a valid IANA timezone"),
        "serve.port": (
            _integer(1, 65535, RESERVED_PORTS),
            "an integer from 1 to 65535" + port,
        ),
        "serve.tailnet_name": (_hostname, "a hostname of letters, digits, hyphens, and dots"),
        "serve.allowed_logins": (
            _logins,
            "a list of logins, as a JSON array of strings or comma-separated",
        ),
        "serve.web_fetch_cap": (_integer(0), "an integer of 0 or more"),
        "serve.max_budget_usd": (_positive_float, "a number greater than 0"),
        "serve.run_timeout_minutes": (_positive_float, "a number greater than 0"),
        "serve.keep_runs": (_integer(0), "an integer of 0 or more"),
        "serve.engines.default": (_choice("claude", "codex"), "claude or codex"),
        "providers.gemini.max_tasks_per_day": (_integer(0), "an integer of 0 or more"),
        "providers.edgar.user_agent": (_text, "non-empty single-line text"),
    }
    for engine in ENGINES:
        prefix = f"serve.engines.{engine}."
        schema[prefix + "model"] = (_token, "a non-empty model name without spaces")
        schema[prefix + "effort"] = (_choice("low", "medium", "high"), "low, medium, or high")
        schema[prefix + "max_budget_usd"] = (_positive_float, "a number greater than 0")
        schema[prefix + "enabled"] = (_boolean, "true or false")
    for provider in PROVIDERS:
        schema[f"providers.{provider}.daily_limit"] = (_integer(0), "an integer of 0 or more")
    return schema


ENGINES = ("claude", "codex")
PROVIDERS = ("alphavantage", "fred", "edgar", "exa", "firecrawl", "gemini")


def config_value(key: str, text: str):
    """The typed value for one settable key, or an invalid_key / invalid_value refusal."""
    schema = _schema()
    if key not in schema:
        raise OfficeError("invalid_key", "That key cannot be set; see the README for the list.")
    parse, expected = schema[key]
    value = parse(text)
    if value is None:
        raise OfficeError("invalid_value", f"{key} expects {expected}.")
    return value


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    return "[" + ", ".join(_toml(item) for item in value) + "]"


HEADER = re.compile(r"[ \t]*\[")
COMMENT_OR_BLANK = re.compile(r"[ \t]*(?:#.*)?\r?\n?")


def _header(table):
    words = r"[ \t]*\.[ \t]*".join(map(re.escape, table.split(".")))
    return re.compile(r"[ \t]*\[[ \t]*" + words + r"[ \t]*\][ \t]*(?:#.*)?\r?\n?")


def _edit(text: str, key: str, value) -> str:
    """The file with one key replaced or added, every other byte untouched.

    Only the line or lines holding that key's value change. A key that is missing is added
    at the end of its table, and a missing table is appended to the file. The caller
    verifies the result parses to the intended settings.
    """
    table, name = key.rsplit(".", 1)
    line = f"{name} = {_toml(value)}\n"
    lines = text.splitlines(keepends=True)
    header = _header(table)
    start = next((i for i, row in enumerate(lines) if header.fullmatch(row)), None)
    if start is None:
        prefix = text if not text or text.endswith("\n") else text + "\n"
        return prefix + ("\n" if prefix.strip() else "") + f"[{table}]\n" + line
    end = next(
        (i for i in range(start + 1, len(lines)) if HEADER.match(lines[i])),
        len(lines),
    )
    assignment = re.compile(r"[ \t]*" + re.escape(name) + r"[ \t]*=")
    for i in range(start + 1, end):
        if assignment.match(lines[i]):
            for j in range(i + 1, end + 1):
                try:
                    tomllib.loads("".join(lines[i:j]))
                except tomllib.TOMLDecodeError:
                    continue
                return "".join(lines[:i]) + line + "".join(lines[j:])
            break
    last = max(
        (i for i in range(start, end) if not COMMENT_OR_BLANK.fullmatch(lines[i])),
        default=start,
    )
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    return "".join(lines[: last + 1]) + line + "".join(lines[last + 1 :])


def _assign(settings: dict, key: str, value) -> dict:
    result = copy.deepcopy(settings)
    node = result
    *path, name = key.split(".")
    for word in path:
        node = node.setdefault(word, {})
        if not isinstance(node, dict):
            raise OfficeError("config_layout", f"{key} sits under a value that is not a table.")
    node[name] = value
    return result


def set_config(root: Path, key: str, text: str) -> dict:
    """Set one schema key in office.toml, atomically and under the office lock.

    The rest of the file, comments included, is kept byte for byte. A layout this edit
    cannot change safely, such as an inline table or dotted keys for the same table, is
    refused rather than rewritten.
    """
    from fo.lock import office_lock

    value = config_value(key, text)
    with office_lock(root, wait=LOCK_WAIT):
        writer_changed = (
            key == "hosts.writer" and read_config(root).get("hosts", {}).get("writer") != value
        )
        _write_config(root, key, value)
    result = {"key": key, "value": value}
    if writer_changed:
        result["note"] = (
            f"Run `fo schedule install` on {value} if it has not been scheduled there. "
            "The old host's sync job will now skip (with --if-writer)."
        )
    return result


def _write_config(root: Path, key: str, value):
    from fo.office import atomic_write

    path = contained(root, "office.toml")
    try:
        original = path.read_text()
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise OfficeError("invalid_config", "office.toml is unreadable.") from exc
    try:
        before = tomllib.loads(original)
    except tomllib.TOMLDecodeError as exc:
        raise OfficeError("invalid_config", "office.toml is not valid TOML.") from exc
    updated = _edit(original, key, value)
    try:
        after = tomllib.loads(updated)
    except tomllib.TOMLDecodeError:
        after = None
    if after != _assign(before, key, value):
        raise OfficeError(
            "config_layout",
            f"office.toml defines {key.rsplit('.', 1)[0]} in a form fo config set "
            "cannot edit safely; change it by hand.",
        )
    if updated != original:
        atomic_write(path, updated, mode)


def get_config(root: Path, key: str) -> dict:
    if key not in _schema():
        raise OfficeError("invalid_key", "That key is not a settable key; see the README.")
    node = read_config(root)
    for word in key.split("."):
        node = node.get(word) if isinstance(node, dict) else None
    return {"key": key, "value": node, "set": node is not None}


LOCK_WAIT = 10.0


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OfficeError(
            "invalid_json", "A required JSON file is unreadable or malformed."
        ) from exc
