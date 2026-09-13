import json
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

import typer

from fo import __version__
from fo.commands import register
from fo.config import public_config
from fo.doctor import diagnose
from fo.errors import OfficeError
from fo.init import initialize
from fo.lock import office_lock
from fo.office import discover


class OfficeGroup(typer.core.TyperGroup):
    """Common flags work before or after command names."""

    def parse_args(self, ctx, args):
        global_args, rest = [], []
        index = 0
        while index < len(args):
            arg = args[index]
            if arg == "--":
                rest.extend(args[index:])
                break
            if arg in ("--json", "--read-only") or arg.startswith("--office="):
                global_args.append(arg)
            elif arg == "--office" and index + 1 < len(args):
                global_args.extend(args[index : index + 2])
                index += 1
            else:
                rest.append(arg)
            index += 1
        return super().parse_args(ctx, global_args + rest)


app = typer.Typer(
    cls=OfficeGroup,
    no_args_is_help=True,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)
skills_app = typer.Typer(no_args_is_help=True)
app.add_typer(skills_app, name="skills")
sync_app = typer.Typer(invoke_without_command=True)
app.add_typer(sync_app, name="sync")


def emit(ctx, result):
    from fo.presentation import human, summary

    if "full" in ctx.obj and not ctx.obj["full"]:
        result = summary(result)
    if ctx.obj["json"]:
        typer.echo(json.dumps(result, ensure_ascii=False, default=str))
    elif isinstance(result, str):
        typer.echo(result)
    else:
        human(result)


def run(ctx, operation: Callable):
    try:
        result = operation()
        emit(ctx, result)
        return result
    except OfficeError as exc:
        emit(ctx, {"reason": exc.reason, "message": exc.message})
        raise typer.Exit(1) from exc
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ArithmeticError,
        sqlite3.Error,
        subprocess.TimeoutExpired,
    ) as exc:
        # Do not expose paths, input snippets, provider bodies, or credentials.
        emit(
            ctx,
            {
                "reason": "operation_failed",
                "message": "Operation failed; check configuration and file permissions.",
            },
        )
        raise typer.Exit(1) from exc


def root(ctx):
    return discover(ctx.obj["office"])


def writable(ctx):
    if ctx.obj["read_only"]:
        raise OfficeError(
            "read_only", "This command writes files and is unavailable in read-only mode."
        )


@app.callback()
def main(
    ctx: typer.Context,
    office: Path | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
    read_only: bool = typer.Option(False, "--read-only"),
    version: bool = typer.Option(False, "--version", is_eager=True),
):
    ctx.obj = {"office": office, "json": json_output, "read_only": read_only}
    if version:
        typer.echo("family-office " + __version__)
        raise typer.Exit()


@app.command("init")
def init_command(ctx: typer.Context, path: Path):
    def execute():
        writable(ctx)
        return initialize(path)

    run(ctx, execute)


@app.command("setup")
def setup_command(
    ctx: typer.Context,
    path: Path,
    provider: list[str] = typer.Option(None),
    offline: bool = typer.Option(False),
):
    from fo.setup import setup

    def execute():
        writable(ctx)
        return setup(path, provider, offline)

    result = run(ctx, execute)
    if result["status"] == "needs_attention":
        raise typer.Exit(1)


@app.command()
def doctor(ctx: typer.Context, notify: bool = False):
    def execute():
        if notify:
            writable(ctx)
        checks = diagnose(root(ctx))
        if notify and any(c["status"] in {"warn", "fail"} for c in checks):
            from fo.operations import notification

            notification("Family Office: diagnostics need attention.")
        return checks

    checks = run(ctx, execute)
    if any(c["status"] == "fail" for c in checks):
        raise typer.Exit(1)


@app.command("config")
def config_command(ctx: typer.Context):
    run(ctx, lambda: public_config(root(ctx)))


@skills_app.command("sync")
def sync_skills(ctx: typer.Context):
    from fo.skills import sync

    def execute():
        writable(ctx)
        office = root(ctx)
        with office_lock(office):
            return sync(office)

    run(ctx, execute)


@app.command("skill")
def print_skill(ctx: typer.Context, name: str, path: Path | None = None):
    from fo.skills import skill_body

    if name == "verify" and path:
        from fo.reports import verify

        run(ctx, lambda: verify(root(ctx), path))
    else:
        run(ctx, lambda: skill_body(name))


@app.command("auth")
def auth_command(ctx: typer.Context, provider: str):
    from fo.auth import authenticate

    def execute():
        writable(ctx)
        office = root(ctx)
        with office_lock(office):
            return authenticate(office, provider)

    run(ctx, execute)


@sync_app.callback()
def sync_command(
    ctx: typer.Context,
    provider: str | None = typer.Option(None),
    dry_run: bool = typer.Option(False),
    full: bool = typer.Option(False),
    commit: bool = typer.Option(False),
    before: str | None = typer.Option(None),
):
    if ctx.invoked_subcommand:
        return
    from fo.sync import synchronize

    def execute():
        writable(ctx)
        return synchronize(root(ctx), provider, dry_run, full, commit, before)

    results = run(ctx, execute)
    if any(r["status"] != "complete" for r in results):
        raise typer.Exit(1)


@sync_app.command("status")
def sync_status(ctx: typer.Context):
    from fo.store.jsonl import read_rows

    run(ctx, lambda: read_rows(root(ctx), "data/sync_log.jsonl"))


@app.command("reindex")
def reindex_command(ctx: typer.Context):
    from fo.store.index import reindex

    def execute():
        writable(ctx)
        return reindex(root(ctx))

    run(ctx, execute)


@app.command("positions")
def positions(
    ctx: typer.Context,
    account: str | None = typer.Option(None),
    symbol: str | None = typer.Option(None),
    full: bool = False,
):
    ctx.obj["full"] = full
    from fo.compute import context

    def execute():
        state = context(root(ctx), ctx.obj["read_only"])
        state["positions"] = [
            p
            for p in state["positions"]
            if (not account or p["account_id"] == account) and (not symbol or p["symbol"] == symbol)
        ]
        state["as_of"] = min((p["as_of"] for p in state["positions"]), default=None)
        return {k: state[k] for k in ("positions", "as_of", "stale_accounts", "stale_providers")}

    run(ctx, execute)


@app.command("commit")
def commit_command(ctx: typer.Context):
    from fo.commits import commit_office

    def execute():
        writable(ctx)
        office = root(ctx)
        with office_lock(office):
            return commit_office(office)

    run(ctx, execute)


register(app)

if __name__ == "__main__":
    app()
