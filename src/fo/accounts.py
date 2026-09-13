"""Register provider-discovered identities without copying private identifiers."""

from fo.errors import OfficeError
from fo.office import contained, write_json
from fo.store.authored import load


def register(root, provider, discovered):
    if not discovered:
        raise OfficeError("no_accounts", "The provider returned no accounts to connect.")
    registry = load(root, "accounts")
    rows = registry["accounts"]
    assigned = []
    for item in discovered:
        key = "provider_ref" if provider == "simplefin" else "last4"
        matches = [r for r in rows if r["provider"] == provider and r.get(key) == item[key]]
        if len(matches) > 1 or (
            provider == "schwab" and sum(d["last4"] == item["last4"] for d in discovered) > 1
        ):
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
        if provider == "simplefin":
            entry["provider_ref"] = item["provider_ref"]
        rows.append(entry)
        assigned.append(entry["id"])
    write_json(contained(root, "profile/accounts.json"), registry)
    return assigned
