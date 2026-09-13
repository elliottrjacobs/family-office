import hashlib
import json
import re
from collections import defaultdict
from datetime import date

from fo.clauses import evaluate, parse
from fo.config import read_config
from fo.errors import OfficeError
from fo.lock import office_lock
from fo.office import atomic_write, contained
from fo.store.jsonl import append, identifier, now, read_rows


def decisions(root):
    rows = {}
    for event in read_rows(root, "notebook/decisions.jsonl"):
        key = event["id"]
        if event["event"] == "created":
            rows[key] = {**event, "status": "open"}
        elif key in rows:
            if event["event"] in {"closed", "reopened"}:
                rows[key].update(event, status="closed" if event["event"] == "closed" else "open")
            elif event["event"] == "reviewed":
                rows[key]["review"] = event
                if event.get("judged_until"):
                    rows[key]["judged_until"] = event["judged_until"]
    return list(rows.values())


def add(
    root,
    subject,
    action,
    thesis,
    invalidate,
    when=None,
    conviction="MEDIUM",
    source="journal",
    report=None,
    context_level="none",
    price_at=None,
):
    if (
        not thesis.strip()
        or not invalidate.strip()
        or conviction.upper() not in {"HIGH", "MEDIUM", "LOW"}
        or context_level not in {"none", "household", "full"}
    ):
        raise OfficeError(
            "invalid_decision", "Supply thesis, invalidation, valid conviction, and context level."
        )
    clauses = [parse(text) for text in when or []]
    event = {
        "id": identifier(),
        "event": "created",
        "as_of": now(),
        "date": date.today().isoformat(),
        "subject": subject,
        "action": action,
        "thesis": thesis,
        "invalidate": invalidate,
        "when": clauses,
        "conviction": conviction.upper(),
        "source": source,
        "report": report,
        "context_level": context_level,
        "price_at": price_at,
        "price_at_as_of": now() if price_at is not None else None,
    }
    with office_lock(root):
        append(root, "notebook/decisions.jsonl", event)
    return event


def transition(root, decision_id, event, outcome=None, note="", judged_until=None):
    with office_lock(root):
        current = next((d for d in decisions(root) if d["id"] == decision_id), None)
        if not current:
            raise OfficeError("unknown_decision", "Decision does not exist.")
        if event == "closed" and (
            current["status"] != "open" or outcome not in {"hit", "miss", "neutral", "unknown"}
        ):
            raise OfficeError(
                "invalid_transition", "Close an open decision with hit, miss, neutral, or unknown."
            )
        if event == "reopened" and (current["status"] != "closed" or not note):
            raise OfficeError("invalid_transition", "Reopen a closed decision with a reason.")
        if judged_until:
            date.fromisoformat(judged_until)
        row = {"id": decision_id, "as_of": now(), "event": event, "note": note}
        if outcome:
            row["outcome"] = outcome
        if judged_until:
            row["judged_until"] = judged_until
        append(root, "notebook/decisions.jsonl", row)
    return row


def corrections(root, skill=None, subject=None, all_scopes=False):
    path = contained(root, "notebook/corrections.md")
    active = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("<!-- fo-correction ") and line.endswith(" -->"):
                row = json.loads(line[len("<!-- fo-correction ") : -4])
                if row["event"] == "retired":
                    active.pop(row["id"], None)
                else:
                    active[row["id"]] = row
    scopes = {"global", f"skill:{skill}", f"subject:{subject}"}
    return [r for r in active.values() if all_scopes or r["scope"] in scopes]


def correct(root, text=None, scope="global", retire=None):
    if not re.fullmatch(r"global|(?:skill|subject):[A-Za-z0-9._-]+", scope):
        raise OfficeError("invalid_scope", "Use global, skill:name, or subject:SYM.")
    if retire is None and (not text or not text.strip()):
        raise OfficeError("invalid_correction", "Correction text is required.")
    with office_lock(root):
        path = contained(root, "notebook/corrections.md")
        old = path.read_text() if path.exists() else "# Standing corrections\n"
        if retire is not None and retire not in {
            r["id"] for r in corrections(root, all_scopes=True)
        }:
            raise OfficeError("unknown_correction", "Active correction does not exist.")
        row = {
            "id": retire
            if retire is not None
            else str(
                1
                + sum(
                    line.startswith("<!-- fo-correction ") and '"event": "added"' in line
                    for line in old.splitlines()
                )
            ),
            "event": "retired" if retire is not None else "added",
            "date": date.today().isoformat(),
            "scope": scope,
            "text": text,
        }
        atomic_write(
            path,
            old
            + "\n<!-- fo-correction "
            + json.dumps(row)
            + " -->\n"
            + (
                f"- {row['date']} [{row['id']}] ({scope}) {text}\n"
                if text
                else f"- Retired {retire}\n"
            ),
        )
    return row


def review(root):
    from fo.compute import allocation
    from fo.market import metric_observations

    with office_lock(root):
        items = decisions(root)
        allocation_result = allocation(root, read_only=True)
        weights = allocation_result["weights"]
        results = []
        for decision in items:
            if decision["status"] != "open":
                continue
            values, results_for_clauses = {}, []
            for clause in decision["when"]:
                metric = clause["metric"]
                if metric == "days_open":
                    observations = [
                        {
                            "value": (date.today() - date.fromisoformat(decision["date"])).days,
                            "as_of": date.today().isoformat(),
                            "source": "decision.date",
                        }
                    ]
                elif metric == "weight":
                    observations = (
                        [
                            {
                                "value": str(weights[decision["subject"]]),
                                "as_of": allocation_result["as_of"],
                                "source": "positions",
                            }
                        ]
                        if weights.get(decision["subject"]) is not None
                        else []
                    )
                else:
                    observations = metric_observations(root, decision["subject"], metric, decision)
                values[metric] = observations
                results_for_clauses.append(evaluate(clause, observations))
            breached = any(value is True for value in results_for_clauses)
            needs = not decision["when"] or any(value is None for value in results_for_clauses)
            suppressed = decision.get("judged_until", "") >= date.today().isoformat()
            results.append(
                {
                    "id": decision["id"],
                    "subject": decision["subject"],
                    "breached": breached,
                    "needs_judgment": needs and not suppressed,
                    "values": values,
                    "due_for_verdict": breached
                    or (date.today() - date.fromisoformat(decision["date"])).days
                    >= read_config(root).get("notebook", {}).get("verdict_days", 180),
                }
            )
        calibration = defaultdict(lambda: {"hit": 0, "miss": 0, "neutral": 0})
        for decision in items:
            if decision["status"] == "closed" and decision.get("outcome") in {
                "hit",
                "miss",
                "neutral",
            }:
                for group in (
                    "conviction:" + decision["conviction"],
                    "source:" + decision["source"],
                ):
                    calibration[group][decision["outcome"]] += 1
        for counts in calibration.values():
            counts["hit_rate"] = counts["hit"] / sum(counts.values())
        payload = {
            "date": date.today().isoformat(),
            "decisions": results,
            "calibration": dict(calibration),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        previous = read_rows(root, "notebook/reviews.jsonl")
        repeated = bool(previous and previous[-1].get("digest") == digest)
        if not repeated:
            for item in results:
                append(
                    root, "notebook/decisions.jsonl", {**item, "event": "reviewed", "as_of": now()}
                )
            append(root, "notebook/reviews.jsonl", {**payload, "digest": digest, "as_of": now()})
        text = (
            f"# Decision review\n\nDate: {payload['date']}\n\n## Breaches\n"
            + "\n".join(f"- {r['subject']} ({r['id']})" for r in results if r["breached"])
            + "\n\n## Needs judgment\n"
            + "\n".join(f"- {r['subject']} ({r['id']})" for r in results if r["needs_judgment"])
            + "\n\n## Due for verdict\n"
            + "\n".join(f"- {r['subject']} ({r['id']})" for r in results if r["due_for_verdict"])
            + "\n\n## Calibration\n\n"
            + json.dumps(dict(calibration), indent=2)
            + "\n"
        )
        atomic_write(contained(root, f"notebook/reviews/{payload['date']}.md"), text)
    return {**payload, "unchanged": repeated, "breaches": sum(r["breached"] for r in results)}
