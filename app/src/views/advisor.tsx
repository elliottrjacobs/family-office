import * as React from "react"
import { CircleAlert, FileText, History, MessageSquare, PanelRight, SquarePen } from "lucide-react"

import { type Advisor, decisions, reports } from "@/api/office"
import {
  ACTIVE,
  cancel,
  converse,
  follow,
  reply,
  run as fetchRun,
  type Run,
  type RunnerStatus,
  runnerStatus,
  runs,
} from "@/api/runs"
import { type Loaded, useApi } from "@/api/use-api"
import { useAppData } from "@/app-data"
import { AdvisorInspector, useInspectorShown } from "@/components/advisor-inspector"
import { AdvisorIcon, advisorName } from "@/components/advisor-icon"
import { ChatHistory, chatHref, chatTitle } from "@/components/chat-history"
import { ChatOptions, useChatSettings } from "@/components/chat-options"
import { Composer } from "@/components/composer"
import { message } from "@/components/confirm-dialog"
import { RecordDecision } from "@/components/decision-actions"
import { Empty, Loading, Page } from "@/components/page"
import { RunEngine, RunView } from "@/components/run-view"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { day } from "@/lib/format"
import { hasNative, native } from "@/lib/native"
import { Link, navigate, reportHref, useLocation } from "@/lib/router"
import { apply, empty, type Transcript } from "@/lib/transcript"

const ONBOARD_OPENER = "Let's set up my office."

/** Things to ask, taken from the quoted examples in the advisor's own description. */
export function starters(advisor: Advisor) {
  return Array.from(advisor.description.matchAll(/'([^']+)'/g), (match) => match[1])
    .slice(0, 4)
    .map((text) => text[0].toUpperCase() + text.slice(1))
}

/** What the advisor is for, without the "Use for ..." examples the starters already show. */
function purpose(advisor: Advisor) {
  return advisor.description.split(/\s+Use for\b/)[0]
}

function Welcome({
  advisor,
  onPick,
  onStart,
}: {
  advisor: Advisor
  onPick: (text: string) => void
  onStart: (text: string) => void
}) {
  const name = advisorName(advisor.name)
  const interview = advisor.name === "onboard"
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 py-10 text-center">
      <AdvisorIcon name={advisor.name} group={advisor.group} className="size-12 rounded-xl [&_svg]:size-6" />
      <h2 className="text-2xl sm:text-3xl">{interview ? "Let's set up your office" : `Ask ${name}`}</h2>
      <p className="max-w-lg text-sm text-pretty text-muted-foreground">
        {interview
          ? "Onboard interviews you about your household, accounts, goals, and taxes, and fills in your profile as you answer. Stop any time; it picks up where you left off."
          : purpose(advisor)}
      </p>
      {interview ? (
        <Button size="lg" onClick={() => onStart(ONBOARD_OPENER)}>
          Start the interview
        </Button>
      ) : (
        <ul className="flex max-w-xl flex-wrap justify-center gap-2" aria-label="Suggestions">
          {starters(advisor).map((text) => (
            <li key={text}>
              <button
                type="button"
                onClick={() => onPick(text)}
                className="rounded-full border bg-card px-3.5 py-1.5 text-sm text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                {text}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Why web access is unavailable for this conversation, or undefined when it can be on. */
function webBlocked(policy: string, level: string, engine: string | undefined) {
  if (policy === "off") return "Web access is turned off for this office."
  if (level === "none") return undefined
  if (policy === "isolated") return "This office allows web access only in chats that read no household data."
  if (engine === "codex") return "Codex cannot use the web in a chat that reads household data."
  return undefined
}

/** One conversation with an advisor: start it, stream it, follow up, stop it. */
function Conversation({
  advisor,
  runId,
  runner,
  history,
}: {
  advisor: Advisor
  runId: string | null
  runner: RunnerStatus
  history: Loaded<Run[]>
}) {
  const { refresh } = useAppData()
  const name = advisorName(advisor.name)
  const journal = useApi("decisions", decisions)
  const record = useApi(`run:${runId ?? "none"}`, () => (runId ? fetchRun(runId) : Promise.resolve(undefined)))
  // The transcript belongs to one run; a different run starts from empty.
  const [held, setHeld] = React.useState<{ run?: string; transcript: Transcript }>({ transcript: empty })
  const transcript = runId && held.run === runId ? held.transcript : empty
  const [generation, setGeneration] = React.useState(0)
  const [draft, setDraft] = React.useState<{ chat: string | null; text: string }>({ chat: runId, text: "" })
  const [pending, setPending] = React.useState<string>()
  const [error, setError] = React.useState<string>()
  const [focus, setFocus] = React.useState(0)
  const [switched, setSwitched] = React.useState<{ chat: string | null; on: boolean }>()
  const { settings, catalog, update } = useChatSettings(advisor, runner.engines ?? [], runner.default)
  const last = React.useRef(0)
  React.useEffect(() => {
    last.current = transcript.last
  })

  const reloadRecord = record.reload
  const reloadJournal = journal.reload
  const reloadHistory = history.reload
  React.useEffect(() => {
    if (!runId) return
    return follow(
      runId,
      last.current,
      (event) => {
        // The stream echoes the message just sent; the placeholder gives way to it.
        if (event.kind === "user") setPending(undefined)
        setHeld((state) => ({
          run: runId,
          transcript: apply(state.run === runId ? state.transcript : empty, event),
        }))
      },
      () => {
        reloadRecord()
        reloadJournal()
        reloadHistory()
        refresh()
      }
    )
  }, [runId, generation, reloadRecord, reloadJournal, reloadHistory, refresh])

  const run = runId ? record.data : undefined
  const status = transcript.status ?? run?.status
  const working = (status !== undefined && ACTIVE.includes(status)) || pending !== undefined
  const elsewhere = history.data?.find((r) => ACTIVE.includes(r.status) && r.id !== runId)
  const text = draft.chat === runId ? draft.text : ""

  const level = run?.level ?? settings.level
  const blocked = webBlocked(runner.web ?? "on", level, run?.engine ?? settings.choice?.engine)
  const stored = run ? run.web_wanted !== false : true
  const webOn = switched && switched.chat === runId ? switched.on : stored

  const send = async (words: string) => {
    setError(undefined)
    setPending(words)
    try {
      if (!runId) {
        const started = await converse(advisor.name, words, {
          level: settings.level,
          // Unset follows the office policy; false is this chat's own switch.
          web: webOn ? undefined : false,
          deep: advisor.deep && Boolean(runner.deep) && settings.deep,
          choice: settings.choice,
        })
        reloadHistory()
        refresh()
        navigate(chatHref(started))
      } else {
        await reply(runId, words, webOn === stored ? undefined : webOn)
        setDraft({ chat: runId, text: "" })
        setGeneration((g) => g + 1)
        reloadRecord()
        reloadHistory()
      }
    } catch (reason) {
      // The text stays in the box so nothing typed is lost.
      setPending(undefined)
      setError(message(reason))
    }
  }

  const stop = async () => {
    if (!runId) return
    try {
      await cancel(runId)
    } catch {
      // Already finished; the record says how.
    }
    reloadRecord()
  }

  const fresh = !runId && !pending
  const unusable = Boolean(runId) && !record.loading && run !== undefined && !run.session_id && !working
  const notice = elsewhere
    ? undefined
    : working
      ? `${name} is answering…`
      : unusable
        ? "This chat cannot continue. Start a new one."
        : undefined

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex flex-1 flex-col pb-4">
        {fresh ? (
          <Welcome
            advisor={advisor}
            onPick={(words) => {
              setDraft({ chat: runId, text: words })
              setFocus((f) => f + 1)
            }}
            onStart={(words) => void send(words)}
          />
        ) : runId && record.error && !run ? (
          <Empty icon={MessageSquare} title="This chat is no longer here">
            <Link to={`/advisors/${advisor.name}`} className="underline underline-offset-4">
              Start a new chat
            </Link>
          </Empty>
        ) : (
          <div className="space-y-5">
            {run && <RunEngine run={run} visits={transcript.web.length} />}
            <RunView
              run={run}
              transcript={transcript}
              decisions={journal.data ?? []}
              pending={pending}
              onResume={() => void send("")}
              onNew={() => navigate(`/advisors/${advisor.name}`)}
            />
          </div>
        )}
      </div>
      <div className="sticky bottom-0 z-[5] -mx-2 bg-gradient-to-t from-background from-80% to-transparent px-2 pt-6 pb-3">
        {error && (
          <p role="alert" className="mb-2 flex items-start gap-2 text-sm text-destructive-foreground">
            <CircleAlert className="mt-0.5 size-4 shrink-0" />
            {error}
          </p>
        )}
        {elsewhere && (
          <p className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
            <span className="min-w-0 flex-1">
              {advisorName(elsewhere.skill)} is answering in “{chatTitle(elsewhere)}”. One advisor works at a time.
            </span>
            <Button variant="outline" size="sm" render={<Link to={chatHref(elsewhere)} />}>
              Open that chat
            </Button>
          </p>
        )}
        <Composer
          key={runId ?? "new"}
          placeholder={
            advisor.name === "onboard" && fresh ? "Or tell Onboard where you want to begin" : `Message ${name}`
          }
          value={text}
          onValueChange={(next) => setDraft({ chat: runId, text: next })}
          onSend={send}
          onStop={runId ? () => void stop() : undefined}
          working={working}
          disabled={Boolean(elsewhere) || unusable}
          notice={notice}
          focusSignal={focus}
          autoFocus
          web={{
            on: webOn,
            available: !blocked,
            reason: blocked,
            onChange: (on) => setSwitched({ chat: runId, on }),
          }}
          options={
            !runId && (
              <ChatOptions
                advisor={advisor}
                settings={settings}
                catalog={catalog}
                engines={runner.engines ?? []}
                deepAvailable={Boolean(runner.deep)}
                onChange={update}
              />
            )
          }
        />
        <p className="mt-2 text-center text-xs text-muted-foreground">
          Advisors can be wrong; check what matters. Nothing here can trade or move money.
        </p>
      </div>
    </div>
  )
}

function ChatUnavailable({ name }: { name: string }) {
  const { status } = useAppData()
  const runner = useApi("runner", runnerStatus)
  if (name === "journal") {
    return (
      <div className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Record a decision with this form; it saves the same fields the journal skill does.
        </p>
        <RecordDecision onDone={() => navigate("/decisions")} />
      </div>
    )
  }
  if (status && !status.chat) {
    return <p className="text-sm text-muted-foreground">Chat is off because the office is open read-only.</p>
  }
  if (runner.loading) return <Loading rows={1} />
  return (
    <div className="space-y-3 text-sm">
      <p>{runner.data?.message ?? runner.error?.message ?? "Chat is unavailable."}</p>
      <p className="text-muted-foreground">
        Advisors answer through Claude Code on this Mac, signed in to your own account. Once it is
        installed and signed in, chat turns on here by itself.
      </p>
      {hasNative() && (
        <Button variant="outline" size="sm" onClick={() => native("settings:engines")}>
          Open Engines settings
        </Button>
      )}
    </div>
  )
}

/** The advisor's earlier chats and what it reads, beside the conversation. */
function SidePanel({
  advisor,
  mine,
  current,
  run,
  history,
  onNavigate,
}: {
  advisor: Advisor
  mine: Run[]
  current: string | null
  run: Run | undefined
  history: Loaded<Run[]>
  onNavigate?: () => void
}) {
  const library = useApi("reports", reports, 60_000)
  const recent = (library.data?.reports ?? [])
    .filter((r) => r.frontmatter.kind === advisor.report_kind)
    .sort((a, b) => (a.frontmatter.date < b.frontmatter.date ? 1 : -1))
    .slice(0, 5)
  return (
    <Tabs defaultValue="chats">
      <TabsList className="mb-2 w-full">
        <TabsTrigger value="chats">Chats</TabsTrigger>
        <TabsTrigger value="about">About</TabsTrigger>
      </TabsList>
      <TabsContent value="chats" className="space-y-3">
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          render={<Link to={`/advisors/${advisor.name}`} onClick={onNavigate} />}
        >
          <SquarePen /> New chat
        </Button>
        {history.loading ? (
          <Loading rows={2} />
        ) : (
          <ChatHistory
            runs={mine}
            current={current}
            onNavigate={onNavigate}
            onDeleted={(id) => {
              history.reload()
              if (id === current) navigate(`/advisors/${advisor.name}`)
            }}
            empty={`No chats with ${advisorName(advisor.name)} yet.`}
          />
        )}
      </TabsContent>
      <TabsContent value="about" className="space-y-6">
        <AdvisorInspector advisor={advisor} run={run} />
        <section className="space-y-2">
          <h3 className="text-xs font-semibold">Recent reports</h3>
          {recent.length ? (
            <ul className="space-y-2">
              {recent.map((r) => (
                <li key={r.path}>
                  <Link
                    to={reportHref(r.path)}
                    onClick={onNavigate}
                    className="flex items-start gap-2 text-[13px] hover:underline"
                  >
                    <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0">
                      {r.frontmatter.subject === "household" ? advisorName(r.frontmatter.kind) : r.frontmatter.subject}
                      <span className="text-muted-foreground">, {day(r.frontmatter.date)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-muted-foreground">No {advisor.report_kind} reports yet.</p>
          )}
        </section>
      </TabsContent>
    </Tabs>
  )
}

export function AdvisorPage({ name }: { name: string }) {
  const { registry, status } = useAppData()
  const { query } = useLocation()
  const current = query.get("chat")
  const runner = useApi(status?.chat ? "runner" : "runner-off", () =>
    status?.chat ? runnerStatus() : Promise.resolve(undefined)
  )
  // Polled so a chat answering elsewhere, or finished on another device, shows up here.
  const history = useApi(status?.chat ? "runs" : "runs-off", () => (status?.chat ? runs() : Promise.resolve([])), 5_000)
  const [panelShown, setPanelShown] = useInspectorShown()
  const [sheet, setSheet] = React.useState(false)
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
  const chat = Boolean(status?.chat && runner.data?.ready && name !== "journal")
  const mine = (history.data ?? []).filter((r) => r.skill === name)
  const run = mine.find((r) => r.id === current)
  const panel = (onNavigate?: () => void) => (
    <SidePanel advisor={advisor} mine={mine} current={current} run={run} history={history} onNavigate={onNavigate} />
  )
  return (
    <div className="mx-auto flex w-full max-w-6xl gap-8 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100svh-4rem)] w-full max-w-3xl min-w-0 flex-col">
        <header className="flex items-center gap-3 py-4">
          <AdvisorIcon name={advisor.name} group={advisor.group} className="size-9 [&_svg]:size-4.5" />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-xl leading-tight">{advisorName(advisor.name)}</h1>
            <p className="truncate text-xs text-muted-foreground">{run ? chatTitle(run) : purpose(advisor)}</p>
          </div>
          {chat && (
            <Button variant="ghost" size="sm" render={<Link to={`/advisors/${advisor.name}`} />}>
              <SquarePen /> New chat
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground lg:hidden"
            aria-label="Chat history"
            title="Chat history"
            onClick={() => setSheet(true)}
          >
            <History />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="hidden text-muted-foreground lg:inline-flex"
            aria-label={panelShown ? "Hide chat history" : "Show chat history"}
            aria-pressed={panelShown}
            title={panelShown ? "Hide chat history" : "Show chat history"}
            onClick={() => setPanelShown(!panelShown)}
          >
            <PanelRight />
          </Button>
        </header>
        {chat ? (
          <Conversation key={name} advisor={advisor} runId={current} runner={runner.data!} history={history} />
        ) : (
          <div className="flex-1 rounded-xl border bg-card p-4 sm:p-5">
            <ChatUnavailable name={name} />
          </div>
        )}
      </div>
      {panelShown && (
        <aside
          aria-label={`${advisorName(advisor.name)} chats`}
          className="sticky top-12 hidden h-[calc(100svh-4rem)] w-72 shrink-0 overflow-y-auto border-l py-4 pl-6 lg:block"
        >
          {panel()}
        </aside>
      )}
      <Sheet open={sheet} onOpenChange={setSheet}>
        <SheetContent side="right" className="overflow-y-auto p-4">
          <SheetHeader className="p-0">
            <SheetTitle>{advisorName(advisor.name)}</SheetTitle>
          </SheetHeader>
          {panel(() => setSheet(false))}
        </SheetContent>
      </Sheet>
    </div>
  )
}
