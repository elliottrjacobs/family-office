"""CLI registration for computations, reports, and notebook workflows."""

import typer


def register(app):
    from fo import compute, market, notebook, reports
    from fo.cli import root, run, writable

    @app.command()
    def networth(
        ctx: typer.Context, by: str = "account", as_of: str | None = None, full: bool = False
    ):
        ctx.obj["full"] = full
        run(ctx, lambda: compute.networth(root(ctx), by, as_of, ctx.obj["read_only"]))

    @app.command()
    def allocation(ctx: typer.Context, full: bool = False):
        ctx.obj["full"] = full
        run(ctx, lambda: compute.allocation(root(ctx), ctx.obj["read_only"]))

    @app.command()
    def concentration(ctx: typer.Context, full: bool = False):
        ctx.obj["full"] = full
        run(ctx, lambda: compute.allocation(root(ctx), ctx.obj["read_only"]))

    @app.command()
    def spend(
        ctx: typer.Context,
        month: str = typer.Option(...),
        category: str | None = None,
        full: bool = False,
    ):
        ctx.obj["full"] = full
        run(ctx, lambda: compute.spend(root(ctx), month, category, ctx.obj["read_only"]))

    @app.command()
    def cashflow(ctx: typer.Context, months: int = 3, full: bool = False):
        ctx.obj["full"] = full
        run(ctx, lambda: compute.cashflow(root(ctx), months, ctx.obj["read_only"]))

    @app.command()
    def goals(ctx: typer.Context, full: bool = False):
        ctx.obj["full"] = full
        run(ctx, lambda: compute.goals(root(ctx), ctx.obj["read_only"]))

    @app.command()
    def lots(ctx: typer.Context, symbol: str, full: bool = False):
        ctx.obj["full"] = full
        run(ctx, lambda: compute.lots(root(ctx), symbol, ctx.obj["read_only"]))

    @app.command()
    def categorize(ctx: typer.Context, full: bool = False):
        ctx.obj["full"] = full
        run(
            ctx,
            lambda: {
                "uncategorized": [
                    r for r in compute.categorized(root(ctx)) if r["category"] == "needs-review"
                ]
            },
        )

    @app.command()
    def quote(ctx: typer.Context, symbols: list[str], full: bool = False):
        ctx.obj["full"] = full
        run(
            ctx,
            lambda: [market.quote(root(ctx), symbol, ctx.obj["read_only"]) for symbol in symbols],
        )

    @app.command()
    def fundamentals(ctx: typer.Context, symbol: str, full: bool = False):
        ctx.obj["full"] = full
        run(ctx, lambda: market.fundamentals(root(ctx), symbol, ctx.obj["read_only"]))

    @app.command()
    def filings(ctx: typer.Context, symbol: str, form: str | None = None, full: bool = False):
        ctx.obj["full"] = full
        run(ctx, lambda: market.filings(root(ctx), symbol, form, ctx.obj["read_only"]))

    @app.command()
    def macro(ctx: typer.Context, series: str, since: str | None = None, full: bool = False):
        ctx.obj["full"] = full
        from fo.providers.market import Market

        def execute():
            result = market.stamped(Market(root(ctx), ctx.obj["read_only"]).series(series))
            if since:
                result["data"]["observations"] = [
                    r for r in result["data"].get("observations", []) if r["date"] >= since
                ]
            return result

        run(ctx, execute)

    @app.command()
    def screen(
        ctx: typer.Context,
        concept: str = typer.Option(...),
        period: str = typer.Option(...),
        minimum: str | None = typer.Option(None, "--min"),
        maximum: str | None = typer.Option(None, "--max"),
        universe: str | None = None,
        limit: int = 20,
        full: bool = False,
    ):
        ctx.obj["full"] = full
        run(
            ctx,
            lambda: market.screen(
                root(ctx), concept, period, minimum, maximum, universe, limit, ctx.obj["read_only"]
            ),
        )

    @app.command()
    def prior(
        ctx: typer.Context, subject: str, kind: str | None = None, exclude: str | None = None
    ):
        run(ctx, lambda: reports.prior(root(ctx), subject, kind, exclude))

    report_app = typer.Typer()
    app.add_typer(report_app, name="report")

    @report_app.command("parts")
    def report_parts(
        ctx: typer.Context,
        kind: str = typer.Option(...),
        subject: str = typer.Option(...),
        slug: str = "report",
    ):
        run(ctx, lambda: reports.parts(root(ctx), kind, subject, slug))

    @report_app.command("path")
    def report_path(
        ctx: typer.Context,
        kind: str = typer.Option(...),
        subject: str = typer.Option(...),
        slug: str = "report",
        part: str | None = None,
    ):
        run(ctx, lambda: reports.report_path(root(ctx), kind, subject, slug, part))

    reports_app = typer.Typer()
    app.add_typer(reports_app, name="reports")

    @reports_app.command("index")
    def reports_index(ctx: typer.Context):
        def execute():
            from fo.store.index import reindex

            writable(ctx)
            reindex(root(ctx))
            return reports.scan(root(ctx))

        result = run(ctx, execute)
        if result["parse_errors"]:
            raise typer.Exit(1)

    journal_app = typer.Typer()
    app.add_typer(journal_app, name="journal")

    @journal_app.command("add")
    def journal_add(
        ctx: typer.Context,
        subject: str,
        action: str = typer.Option(...),
        thesis: str = typer.Option(...),
        invalidate: str = typer.Option(...),
        when: list[str] = typer.Option(None),
        conviction: str = "MEDIUM",
        source: str = "journal",
        report: str | None = None,
        context_level: str = "none",
        price_at: str | None = None,
    ):
        def execute():
            writable(ctx)
            return notebook.add(
                root(ctx),
                subject,
                action,
                thesis,
                invalidate,
                when,
                conviction,
                source,
                report,
                context_level,
                price_at,
            )

        run(ctx, execute)

    @journal_app.command("list")
    def journal_list(
        ctx: typer.Context,
        open_only: bool = typer.Option(False, "--open"),
        subject: str | None = None,
    ):
        run(
            ctx,
            lambda: [
                d
                for d in notebook.decisions(root(ctx))
                if (not open_only or d["status"] == "open")
                and (not subject or d["subject"] == subject)
            ],
        )

    @journal_app.command("close")
    def close(
        ctx: typer.Context, decision_id: str, outcome: str = typer.Option(...), note: str = ""
    ):
        def execute():
            writable(ctx)
            return notebook.transition(root(ctx), decision_id, "closed", outcome, note)

        run(ctx, execute)

    @journal_app.command("reopen")
    def reopen(ctx: typer.Context, decision_id: str, reason: str = typer.Option(...)):
        def execute():
            writable(ctx)
            return notebook.transition(root(ctx), decision_id, "reopened", note=reason)

        run(ctx, execute)

    @journal_app.command("judge")
    def judge(ctx: typer.Context, decision_id: str, until: str = typer.Option(...), note: str = ""):
        def execute():
            writable(ctx)
            return notebook.transition(
                root(ctx), decision_id, "reviewed", note=note, judged_until=until
            )

        run(ctx, execute)

    @app.command()
    def review(ctx: typer.Context, notify: bool = False):
        def execute():
            writable(ctx)
            result = notebook.review(root(ctx))
            if notify and result["breaches"]:
                from fo.operations import notification

                notification("Family Office: decisions need review.")
            return result

        result = run(ctx, execute)
        if result["breaches"]:
            raise typer.Exit(1)

    corrections_app = typer.Typer()
    app.add_typer(corrections_app, name="corrections")

    @corrections_app.command("add")
    def correction_add(ctx: typer.Context, text: str, scope: str = "global"):
        def execute():
            writable(ctx)
            return notebook.correct(root(ctx), text, scope)

        run(ctx, execute)

    @corrections_app.command("retire")
    def correction_retire(ctx: typer.Context, correction_id: str):
        def execute():
            writable(ctx)
            return notebook.correct(root(ctx), retire=correction_id)

        run(ctx, execute)

    @corrections_app.command("list")
    def correction_list(
        ctx: typer.Context,
        skill: str | None = None,
        subject: str | None = typer.Option(None, "--for"),
    ):
        run(ctx, lambda: notebook.corrections(root(ctx), skill, subject))

    @app.command()
    def brief(
        ctx: typer.Context,
        level: str = "household",
        subject: str | None = typer.Option(None, "--for"),
        skill: str | None = None,
        full: bool = False,
    ):
        from fo.brief import brief

        run(ctx, lambda: brief(root(ctx), level, subject, skill, full))

    @app.command()
    def start(
        ctx: typer.Context,
        skill: str,
        subject: str = typer.Argument("household"),
        level: str | None = None,
    ):
        from fo.brief import start

        result = run(ctx, lambda: start(root(ctx), skill, subject, level))
        if any(r["status"] == "failed" for r in result.values()):
            raise typer.Exit(1)

    @app.command()
    def score(ctx: typer.Context, symbol: str, playbook: list[str] = typer.Option(...)):
        from fo.playbooks import score

        run(ctx, lambda: score(root(ctx), symbol, playbook, ctx.obj["read_only"]))

    @app.command("score-portfolio")
    def score_portfolio(ctx: typer.Context, playbook: str = "all-weather"):
        from fo.playbooks import score_portfolio

        run(ctx, lambda: score_portfolio(root(ctx), playbook, ctx.obj["read_only"]))

    playbooks_app = typer.Typer()
    app.add_typer(playbooks_app, name="playbooks")

    @playbooks_app.command("list")
    def playbooks_list(ctx: typer.Context):
        from fo.playbooks import listing

        run(ctx, lambda: listing(root(ctx)))

    schedule_app = typer.Typer()
    app.add_typer(schedule_app, name="schedule")

    @schedule_app.command("install")
    def schedule_install(ctx: typer.Context):
        from fo.operations import schedule

        def execute():
            writable(ctx)
            return schedule(root(ctx))

        run(ctx, execute)

    @app.command()
    def notify(ctx: typer.Context, message: str):
        from fo.operations import notification

        def execute():
            writable(ctx)
            return notification(message)

        run(ctx, execute)

    @app.command("export")
    def export_command(ctx: typer.Context):
        run(ctx, lambda: compute.context(root(ctx), ctx.obj["read_only"]))

    @app.command("migrate-v1")
    def migrate_v1(ctx: typer.Context, source: str, dry_run: bool = False, force: bool = False):
        from fo.migrate_v1 import migrate

        def execute():
            if not dry_run:
                writable(ctx)
            return migrate(root(ctx), source, dry_run, force)

        result = run(ctx, execute)
        if result["issues"]:
            raise typer.Exit(1)
