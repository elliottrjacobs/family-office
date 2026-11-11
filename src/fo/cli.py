import os
from collections.abc import Callable
from pathlib import Path

import typer

from fo import __version__
from fo.commands import register
from fo.config import public_config
from fo.doctor import diagnose
from fo.envelope import SAFE_FAILURES, encode, failure
from fo.errors import OfficeError
from fo.init import initialize
from fo.lock import office_lock
from fo.office import discover, run_office


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
        # The advisor-run guard in main() needs the command words without global flags.
        ctx.meta["fo.args"] = rest
        return super().parse_args(ctx, global_args + rest)


app = typer.Typer(
    cls=OfficeGroup,
    no_args_is_help=True,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
    # Typer's eager completion options run before the advisor-run check and write shell
    # startup files; the CLI does not offer them.
    add_completion=False,
)
skills_app = typer.Typer(no_args_is_help=True)
app.add_typer(skills_app, name="skills")
sync_app = typer.Typer(invoke_without_command=True)
app.add_typer(sync_app, name="sync")
config_app = typer.Typer(invoke_without_command=True)
app.add_typer(config_app, name="config")

research_app = typer.Typer(no_args_is_help=True)
app.add_typer(research_app, name="research")


def emit(ctx, result):
    from fo.presentation import human, summary

    if "full" in ctx.obj and not ctx.obj["full"]:
        result = summary(result)
    if ctx.obj["json"]:
        typer.echo(encode(result))
    elif isinstance(result, str):
        typer.echo(result)
    else:
        human(result)


def run(ctx, operation: Callable):
    try:
        result = operation()
        emit(ctx, result)
        return result
    except (OfficeError, *SAFE_FAILURES) as exc:
        # The envelope never exposes paths, input snippets, provider bodies, or credentials.
        emit(ctx, failure(exc))
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
    try:
        ctx.obj["office"] = run_office(office, ctx.meta.get("fo.args", []))
    except OfficeError as exc:
        emit(ctx, failure(exc))
        raise typer.Exit(1) from exc


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
def doctor(ctx: typer.Context, notify: bool = False, fix: bool = False):
    def execute():
        if notify or fix:
            writable(ctx)
        if fix:
            from fo.config import ensure_credentials

            directory = ensure_credentials(root(ctx))
            if not os.environ.get("FO_CREDENTIALS_HOME"):
                directory.parent.chmod(0o700)
            for path in directory.rglob("*"):
                if not path.is_symlink():
                    path.chmod(0o700 if path.is_dir() else 0o600)
        checks = diagnose(root(ctx))
        if notify and any(c["status"] in {"warn", "fail"} for c in checks):
            from fo.operations import notification

            notification("Family Office: diagnostics need attention.")
        return checks

    checks = run(ctx, execute)
    if any(c["status"] == "fail" for c in checks):
        raise typer.Exit(1)


@config_app.callback()
def config_command(ctx: typer.Context):
    """Print settings with secrets masked; set or get one settable key."""
    if ctx.invoked_subcommand:
        return
    run(ctx, lambda: public_config(root(ctx)))


@config_app.command("set")
def config_set(ctx: typer.Context, key: str, value: str):
    """Set one office.toml key from the schema in the README."""
    from fo.config import set_config

    def execute():
        writable(ctx)
        return set_config(root(ctx), key, value)

    run(ctx, execute)


@config_app.command("get")
def config_get(ctx: typer.Context, key: str):
    from fo.config import get_config

    run(ctx, lambda: get_config(root(ctx), key))


@app.command("status")
def status_command(
    ctx: typer.Context,
    lock: bool = typer.Option(
        False, "--lock", help="Probe the office lock; a writer starting meanwhile fails."
    ),
):
    from fo.operations import status

    run(ctx, lambda: status(root(ctx), ctx.obj["read_only"], lock))


@skills_app.command("sync")
def sync_skills(ctx: typer.Context):
    from fo.skills import sync

    def execute():
        writable(ctx)
        office = root(ctx)
        with office_lock(office):
            return sync(office)

    run(ctx, execute)


@skills_app.command("list")
def list_skills(ctx: typer.Context):
    from fo.skills import registry

    run(ctx, registry)


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
    from fo.config import ensure_credentials

    def execute():
        writable(ctx)
        office = root(ctx)
        ensure_credentials(office)
        with office_lock(office):
            return authenticate(office, provider)

    run(ctx, execute)


@app.command("connect")
def connect_command(
    ctx: typer.Context,
    provider: str,
    remove: bool = typer.Option(False, "--remove", help="Delete the stored key or contact."),
    user_agent: str | None = typer.Option(
        None, "--user-agent", help='EDGAR only: "Name email@example.com".'
    ),
):
    """Store a provider API key read from standard input, after one validating call."""
    from fo import connect

    def execute():
        writable(ctx)
        office = root(ctx)
        name = connect.provider_name(provider)
        if remove:
            return connect.remove(office, name)
        if name == "edgar":
            return connect.edgar(office, user_agent)
        return connect.store(office, name, read_key(name))

    run(ctx, execute)


def read_key(provider):
    import sys

    if sys.stdin is None:
        return ""
    if sys.stdin.isatty():
        return typer.prompt(provider + " API key", hide_input=True, err=True)
    return sys.stdin.read(4096)


@research_app.command("search")
def research_search(
    ctx: typer.Context, query: str, limit: int = typer.Option(10, help="Results, 1 to 25.")
):
    """Ranked web results from Exa, as untrusted text."""
    from fo import research

    run(ctx, lambda: research.search(root(ctx), query, limit, ctx.obj["read_only"]))


@research_app.command("fetch")
def research_fetch(ctx: typer.Context, url: str):
    """One page as markdown through Firecrawl, or a direct fetch, as untrusted text."""
    from fo import research

    run(ctx, lambda: research.fetch(root(ctx), url, ctx.obj["read_only"]))


@research_app.command("deep")
def research_deep(
    ctx: typer.Context,
    question: str,
    report: str | None = typer.Option(
        None, "--report", help="Save the result as an inputs part of this report."
    ),
    timeout_minutes: float | None = typer.Option(
        None, "--timeout-minutes", help="Default: [serve] run_timeout_minutes less 5."
    ),
):
    """A Gemini Deep Research task, submitted once and polled to a deadline."""
    from fo import research

    def execute():
        writable(ctx)
        return research.deep(root(ctx), question, report, timeout_minutes)

    result = run(ctx, execute)
    if result.get("reason") == "timed_out":
        raise typer.Exit(1)


@sync_app.callback()
def sync_command(
    ctx: typer.Context,
    provider: str | None = typer.Option(None),
    dry_run: bool = typer.Option(False),
    full: bool = typer.Option(False),
    commit: bool = typer.Option(False),
    before: str | None = typer.Option(None),
    if_writer: bool = typer.Option(
        False, "--if-writer", help="Skip unless this host is the writer."
    ),
):
    if ctx.invoked_subcommand:
        return
    from fo.sync import synchronize

    def execute():
        writable(ctx)
        return synchronize(root(ctx), provider, dry_run, full, commit, before, if_writer=if_writer)

    results = run(ctx, execute)
    if any(r["status"] not in {"complete", "skipped"} for r in results):
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
    from fo.compute import positions as compute_positions

    run(ctx, lambda: compute_positions(root(ctx), account, symbol, ctx.obj["read_only"]))


@app.command("serve")
def serve_command(
    ctx: typer.Context,
    port: int | None = typer.Option(None, help="Default 4790, or port under serve in office.toml."),
    host: str | None = typer.Option(None, help="Bind address; anything but loopback warns."),
    remote: bool = typer.Option(
        False, "--remote", help="Also accept the tailnet name configured for tailscale serve."
    ),
    open_browser: bool = typer.Option(False, "--open", help="Open the app in a browser."),
    app_mode: bool = typer.Option(
        False, "--app", help="Print one JSON handshake line first, for the Mac app."
    ),
    parent_pid: int | None = typer.Option(
        None,
        "--parent-pid",
        help="Stop when this process is gone, so a crashed app leaves no server.",
    ),
):
    """Start the companion web app for this office on 127.0.0.1."""
    from fo.serve import serve

    run(
        ctx,
        lambda: serve(
            ctx.obj["office"],
            port,
            host,
            remote,
            open_browser,
            ctx.obj["read_only"],
            app_mode,
            parent_pid,
        ),
    )


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
