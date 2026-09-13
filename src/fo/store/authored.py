import json
import re
from importlib.resources import files

import jsonschema
import yaml

from fo.errors import OfficeError
from fo.office import contained

PROFILE_FILES = {
    "household": "household.md",
    "ips": "ips.json",
    "goals": "goals.json",
    "tax": "tax.json",
    "accounts": "accounts.json",
    "categories": "categories.yaml",
    "universes": "universes.yaml",
}


def load(root, name):
    path = contained(root, "profile/" + PROFILE_FILES[name])
    try:
        text = path.read_text()
        if name == "household":
            blocks = re.findall(r"^```json\s*\n(.*?)^```", text, re.M | re.S)
            if len(blocks) != 1:
                raise ValueError("one JSON block required")
            value = json.loads(blocks[0])
        elif path.suffix == ".yaml":
            value = yaml.safe_load(text)
        else:
            value = json.loads(text)
        schema = json.loads(files("fo").joinpath(f"store/schemas/{name}.schema.json").read_text())
        jsonschema.Draft202012Validator(schema).validate(value)
        if name == "ips":
            for i, band in enumerate(value.get("bands", [])):
                if band["min"] > band["max"]:
                    raise OfficeError("invalid_profile", f"ips: /bands/{i}/min exceeds max.")
        if name == "accounts":
            ids = [a["id"] for a in value["accounts"]]
            if len(ids) != len(set(ids)):
                raise OfficeError("invalid_profile", "accounts: duplicate account ids.")
        return value
    except OfficeError:
        raise
    except jsonschema.ValidationError as exc:
        pointer = "/" + "/".join(map(str, exc.absolute_path))
        raise OfficeError("invalid_profile", f"{name}: schema violation at {pointer}.") from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise OfficeError("invalid_profile", f"{name}: unreadable or malformed profile.") from exc
