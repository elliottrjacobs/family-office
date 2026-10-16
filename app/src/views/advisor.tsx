import * as React from "react"
import { Check, FileText, MessageSquare, Plus, Terminal } from "lucide-react"

import { decisions, levels, reports } from "@/api/office"
import { cancel, follow, reply, run as fetchRun, runnerStatus, runs } from "@/api/runs"
import { useApi } from "@/api/use-api"
import { useAppData } from "@/app-data"
import { AdvisorIcon, advisorName, GROUP_LABELS } from "@/components/advisor-icon"
import { CommandLine } from "@/components/command-line"
import { RecordDecision } from "@/components/decision-actions"
import { LaunchPanel } from "@/components/launch-panel"
import { Empty, Loading, Page } from "@/components/page"
import { RunView } from "@/components/run-view"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { day } from "@/lib/format"
import { Link, navigate, reportHref } from "@/lib/router"
import { apply, empty, type Transcript } from "@/lib/transcript"

const TIERS = { fast: "Fast model", balanced: "Balanced model", strong: "Strongest model" }

/** The conversation with one advisor: launch, stream, follow up, cancel, resume. */
function Chat({ name, deepAvailable }: { name: string; deepAvailable: boolean }) {
  const { registry, refresh } = useAppData()
  const advisor = registry!.skills.find((a) => a.name === name)!
  const history = useApi("runs", runs)
  const journal = useApi("decisions", decisions)
  // undefined follows the latest run for this advisor; null starts a new one.
  const [chosen, setChosen] = React.useState<string | null | undefined>(undefined)
  const latest = history.data?.find((r) => r.skill === name)?.id
  const runId = chosen === undefined ? latest : chosen
  const record = useApi(`run:${runId ?? "none"}`, () => (runId ? fetchRun(runId) : Promise.resolve(undefined)))
  // The transcript belongs to one run; a different run starts from empty.
  const [held, setHeld] = React.useState<{ run?: string; transcript: Transcript }>({ transcript: empty })
  const transcript = held.run === runId ? held.transcript : empty
  const [generation, setGeneration] = React.useState(0)
  const last = React.useRef(0)
  React.useEffect(() => {
    last.current = transcript.last
  })

  const reloadRecord = record.reload
  const reloadJournal = journal.reload
  React.useEffect(() => {
    if (!runId) return
    return follow(
      runId,
      last.current,
      (event) =>
        setHeld((state) => ({
          run: runId,
          transcript: apply(state.run === runId ? state.transcript : empty, event),
        })),
      () => {
        reloadRecord()
        reloadJournal()
        refresh()
      }
    )
  }, [runId, generation, reloadRecord, reloadJournal, refresh])

  if (history.loading) return <Loading rows={2} />
  if (!runId) {
    return (
      <LaunchPanel
        advisor={advisor}
        deepAvailable={deepAvailable}
        onLaunched={(started) => {
          setChosen(started.id)
          history.reload()
        }}
      />
    )
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {record.data ? `${record.data.subject}, ${record.data.level} context${record.data.deep ? ", deep" : ""}, started ${day(record.data.created)}` : ""}
        </p>
        <Button variant="outline" size="sm" onClick={() => setChosen(null)}>
          <Plus /> New conversation
        </Button>
      </div>
      <RunView
        run={record.data}
        transcript={transcript}
        decisions={journal.data ?? []}
        onNew={() => setChosen(null)}
        onReply={async (text) => {
          await reply(runId, text)
          setGeneration((g) => g + 1)
          record.reload()
        }}
        onCancel={async () => {
          await cancel(runId)
          record.reload()
        }}
      />
    </div>
  )
}

function ChatUnavailable({ name }: { name: string }) {
  const { status } = useAppData()
  const runner = useApi("runner", runnerStatus)
  if (name === "onboard") {
    return (
      <div className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Onboarding is an interview that writes your profile, so it runs in a terminal. Start it
          from your coding agent in the office folder:
        </p>
        <CommandLine command="/onboard" />
      </div>
    )
  }
  if (name === "journal") {
    return (
      <div className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          In the app, record a decision with the form; it saves the same fields the journal
          skill does.
        </p>
        <RecordDecision onDone={() => navigate("/decisions")} />
      </div>
    )
  }
  if (status && !status.chat) {
    return <p className="text-sm text-muted-foreground">Chat is off because fo serve was started with --read-only.</p>
  }
  if (runner.loading) return <Loading rows={1} />
  return (
    <div className="space-y-2 text-sm">
      <p>{runner.data?.message ?? runner.error?.message ?? "Chat is unavailable."}</p>
      <p className="text-muted-foreground">
        Chat runs the advisor with Claude Code on this machine. Install or update it, sign in
        once in a terminal, then reload this page.
      </p>
    </div>
  )
}

export function AdvisorPage({ name }: { name: string }) {
  const { registry, status } = useAppData()
  const table = useApi("levels", levels)
  const library = useApi("reports", reports, 60_000)
  const runner = useApi(status?.chat ? "runner" : "runner-off", () =>
    status?.chat ? runnerStatus() : Promise.resolve(undefined)
  )
  if (!registry) {
    return (
      <Page>
        <Loading />
      </Page>
    )
  }
  const advisor = registry.skills.find((a) => a.name === name)
  if (!advisor) {
    return (
      <Page>
        <Empty icon={MessageSquare} title="No such advisor">
          <Link to="/" className="underline underline-offset-4">
            Back to Home
          </Link>
        </Empty>
      </Page>
    )
  }
  const reads = table.data?.[advisor.default_context]
  const recent = (library.data?.reports ?? [])
    .filter((r) => r.frontmatter.kind === advisor.report_kind)
    .sort((a, b) => (a.frontmatter.date < b.frontmatter.date ? 1 : -1))
    .slice(0, 5)
  const chat = Boolean(status?.chat && runner.data?.ready && !["onboard", "journal"].includes(name))
  return (
    <Page>
      <div className="mb-6 flex items-start gap-3">
        <AdvisorIcon name={advisor.name} group={advisor.group} className="size-10 [&_svg]:size-5" />
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl sm:text-3xl">{advisorName(advisor.name)}</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">{advisor.description}</p>
          <div className="flex flex-wrap gap-1.5 pt-1">
            <Badge variant="outline">{GROUP_LABELS[advisor.group]}</Badge>
            <Badge variant="outline">{TIERS[advisor.tier]}</Badge>
            {advisor.deep && <Badge variant="secondary">Deep mode</Badge>}
            {advisor.invocation === "explicit" && <Badge variant="outline">Runs only when asked</Badge>}
          </div>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <div className="min-w-0 space-y-4">
          <section className="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <MessageSquare className="size-4 text-muted-foreground" /> Ask {advisorName(advisor.name)}
            </h2>
            {chat ? <Chat key={name} name={name} deepAvailable={Boolean(runner.data?.deep)} /> : <ChatUnavailable name={name} />}
          </section>
          <section className="rounded-xl border bg-card p-4 sm:p-5">
            <h2 className="mb-3 text-base font-semibold">Recent reports</h2>
            {recent.length ? (
              <ul className="space-y-2">
                {recent.map((r) => (
                  <li key={r.path}>
                    <Link to={reportHref(r.path)} className="flex items-start gap-2 text-sm hover:underline">
                      <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0">
                        <span className="font-medium">
                          {r.frontmatter.subject === "household" ? advisorName(r.frontmatter.kind) : r.frontmatter.subject}
                        </span>
                        <span className="text-muted-foreground">, {day(r.frontmatter.date)}</span>
                        <span className="block truncate text-xs text-muted-foreground">{r.summary}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No {advisor.report_kind} reports yet.</p>
            )}
          </section>
        </div>
        <aside className="space-y-4 self-start rounded-xl border bg-card p-4 sm:p-5">
          <div>
            <h2 className="text-base font-semibold">What {advisorName(advisor.name)} reads</h2>
            <p className="text-xs text-muted-foreground">
              Default context: {advisor.default_context}. Allowed: {advisor.allowed_context.join(", ")}.
            </p>
          </div>
          {reads ? (
            <ul className="space-y-1.5 text-sm">
              {reads.reads.map((line) => (
                <li key={line} className="flex gap-2">
                  <Check className="mt-0.5 size-3.5 shrink-0 text-success-foreground" />
                  {line}
                </li>
              ))}
            </ul>
          ) : (
            <Loading rows={1} />
          )}
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Commands</p>
            <ul className="space-y-1">
              {advisor.commands.map((command) => (
                <li key={command}>
                  <code className="flex items-center gap-1.5 font-mono text-xs">
                    <Terminal className="size-3 text-muted-foreground" />
                    fo {command} --json
                  </code>
                </li>
              ))}
            </ul>
          </div>
          <p className="text-xs text-muted-foreground">Writes {advisor.report_kind} reports under reports/.</p>
        </aside>
      </div>
    </Page>
  )
}
