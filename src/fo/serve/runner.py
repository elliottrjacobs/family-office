"""The agent-runner contract for advisor chat, and the event shape the server stores.

A runner turns an office, a prompt, and an optional session to resume into a process
whose stdout is parsed into events. Claude Code headless is the one implementation;
another host would add its own module with the same methods.

Events are plain dicts with a "kind":
  init         session_id, model, and the isolation facts the run manager checks
  user         text sent to the advisor
  text         assistant text; "delta" carries streamed pieces and is never stored
  tool         id, name, label (a short description of the call), command or path
  tool_result  id, ok, output (truncated)
  result       ok, subtype, text, cost_usd, turns, session_id, denials
  web          action ("fetch" or "search") and value (the URL or query), folded in by
               the run manager from the guard hook's web.jsonl in the run folder

`web` is true only at context level none: the runner then offers its web tools, and the
guard hook, which reads FO_SERVE_RUN_DIR, FO_SERVE_WEB, and FO_SERVE_WEB_FETCH_CAP from
the environment the runner builds, checks, caps, and logs each web call.
"""

import json
import re
from importlib.resources import files
from typing import Protocol

from fo.store.jsonl import FORBIDDEN

OUTPUT_LIMIT = 2000
# What the runner's environment tells the guard hook about the run.
RUN_FOLDER = "FO_SERVE_RUN_DIR"
WEB_FLAG = "FO_SERVE_WEB"
FETCH_CAP = "FO_SERVE_WEB_FETCH_CAP"
# Claude's PreToolUse hook already caps/logs research; the CLI still validates it.
# Codex leaves this unset so the CLI owns cap/log accounting for its fo commands.
HOOK_FLAG = "FO_SERVE_HOOK_ACTIVE"
WEB_LOG = "web.jsonl"


class Runner(Protocol):
    name: str

    def preflight(self) -> dict: ...

    def check(self, init: dict, skill: str, web: bool = False) -> str | None: ...

    def settings(self, office, web: bool = False) -> str: ...

    def command(
        self,
        office,
        settings: str,
        budget: float,
        session=None,
        model=None,
        effort=None,
        *,
        web: bool = False,
    ) -> list[str]: ...

    def environment(
        self, office, folder=None, web: bool = False, web_fetch_cap: int = 0
    ) -> dict: ...

    def parse(self, line: str, office) -> list[dict]: ...


def profile():
    """The permission rules every run starts from; see permission_profile.json."""
    data = json.loads(files("fo.serve").joinpath("permission_profile.json").read_text())
    return {"allow": data["allow"], "deny": data["deny"]}


CREDENTIAL_URL = re.compile(r"https?://\S+@\S+")
# Account and card numbers run 12 digits or more; shorter runs are amounts that must stay
# exact in the conversation (fo prints whole-dollar values without separators).
LONG_NUMBER = re.compile(r"\b\d{12,}\b")


def scrub_text(text):
    text = CREDENTIAL_URL.sub("[credential URL omitted]", text)
    return LONG_NUMBER.sub(lambda match: "…" + match[0][-4:], text)


def scrub(value):
    """Event text is untrusted: drop credential-shaped keys and mask credential text."""
    if isinstance(value, dict):
        return {
            key: scrub(item)
            for key, item in value.items()
            if str(key).replace("_", "").replace("-", "").lower() not in FORBIDDEN
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value
