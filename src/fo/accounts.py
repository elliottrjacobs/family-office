"""Register provider-discovered identities without copying private identifiers."""

from fo.commits import record
from fo.errors import OfficeError
from fo.office import contained, write_json
from fo.store.authored import load

# Providers whose accounts are matched by an opaque provider id rather than the last four.
REFERENCED = {"simplefin", "plaid"}
# Providers fo no longer connects to directly; their registered accounts stop syncing.
RETIRED = {
    "schwab": (
        "Schwab now connects through Plaid. Run fo auth plaid and link Schwab, then remove "
        "the old schwab accounts from profile/accounts.json so they are not counted twice."
    )
}


def register(root, provider, discovered):
    """Persist discovered identities and record them while the caller holds office_lock."""
    if not discovered:
        raise OfficeError("no_accounts", "The provider returned no accounts to connect.")
    registry = load(root, "accounts")
    rows = registry["accounts"]
    assigned = []
    for item in discovered:
        key = "provider_ref" if provider in REFERENCED else "last4"
        matches = [r for r in rows if r["provider"] == provider and r.get(key) == item[key]]
        if len(matches) > 1:
            raise OfficeError(
                "ambiguous_account",
                "Provider account identities are ambiguous; existing mappings were preserved.",
            )
        if matches:
            assigned.append(matches[0]["id"])
            continue
        number = 1
        while any(r["id"] == f"{provider}-{number}" for r in rows):
            number += 1
        entry = {"id": f"{provider}-{number}", "provider": provider, "last4": item.get("last4", "")}
        if provider in REFERENCED:
            entry["provider_ref"] = item["provider_ref"]
        # A provider that knows the account kind seeds it; later edits are never overwritten.
        for field in ("type", "role"):
            if item.get(field):
                entry[field] = item[field]
        rows.append(entry)
        assigned.append(entry["id"])
    write_json(contained(root, "profile/accounts.json"), registry)
    record(root, ["profile/accounts.json"], f"Register {provider} accounts")
    return assigned
