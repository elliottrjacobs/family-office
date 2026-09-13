import json
import tomllib
from pathlib import Path

from fo.errors import OfficeError
from fo.office import contained


def read_config(root: Path) -> dict:
    try:
        return tomllib.loads(contained(root, "office.toml").read_text())
    except (OSError, ValueError) as exc:
        raise OfficeError("invalid_config", "office.toml is unreadable or invalid TOML.") from exc


def read_secrets(root: Path) -> dict:
    path = contained(root, "secrets/keys.toml")
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OfficeError(
            "invalid_secrets", "The secrets file is unreadable or invalid TOML."
        ) from exc


def masked(value):
    if isinstance(value, dict):
        return {key: masked(item) for key, item in value.items()}
    if isinstance(value, list):
        return [masked(item) for item in value]
    return "***"


def public_config(root: Path) -> dict:
    return {"settings": read_config(root), "secrets": masked(read_secrets(root))}


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OfficeError(
            "invalid_json", "A required JSON file is unreadable or malformed."
        ) from exc
