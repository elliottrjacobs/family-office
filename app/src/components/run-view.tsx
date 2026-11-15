import * as React from "react"
import {
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  FileText,
  Globe,
  Loader2,
  Play,
  Scale,
  Search,
} from "lucide-react"

import type { Decision } from "@/api/office"
import { ACTIVE, engineLabel, type Run } from "@/api/runs"
import { LEVEL_LABELS } from "@/components/chat-options"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { action as actionLabel } from "@/lib/format"
import { Markdown } from "@/lib/markdown"
import { Link, reportHref } from "@/lib/router"
import type { Item, Step, Transcript, Visit } from "@/lib/transcript"

function Steps({ steps }: { steps: Step[] }) {
  const failed = steps.filter((s) => s.ok === false).length
  return (
    <Collapsible className="group/steps rounded-lg border bg-card text-sm">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted-foreground">
        <ChevronRight className="size-4 transition-transform group-data-[open]/steps:rotate-90" />
        <span>
          {steps.some((s) => s.ok === undefined) ? "Working: " : "Worked through "}
          {steps.length} {steps.length === 1 ? "step" : "steps"}
        </span>
        {failed > 0 && <Badge variant="outline">{failed} refused or failed</Badge>}
        {steps.some((s) => s.ok === undefined) && <Loader2 className="ml-auto size-3.5 animate-spin" />}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="space-y-1 border-t px-3 py-2">
          {steps.map((step) => (
            <li key={step.id} className={`flex items-start gap-2 text-xs ${step.nested ? "pl-5" : ""}`}>
              {step.ok === undefined ? (
                <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin text-muted-foreground" />
              ) : step.ok ? (
                <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-success-foreground" />
              ) : (
                <CircleX className="mt-0.5 size-3.5 shrink-0 text-destructive-foreground" />
              )}
              <span className="min-w-0">
                <span className="break-words">{step.label}</span>
                {step.ok === false && step.output && (
                  <span className="block truncate text-muted-foreground">{step.output.split("\n")[0]}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}

function DecisionCard({ id, decisions }: { id: string; decisions: Map<string, Decision> }) {
  const decision = decisions.get(id)
  return (
    <div className="flex gap-3 rounded-lg border bg-card p-3 text-sm">
      <Scale className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 space-y-1">
        <p className="font-medium">
          Recorded: {decision ? `${actionLabel(decision.action)} ${decision.subject}` : id}
        </p>
        {decision && <p className="text-muted-foreground">{decision.thesis}</p>}
        {decision && <p className="text-xs text-muted-foreground">Invalidate if: {decision.invalidate}</p>}
        <Link to="/decisions" className="text-xs underline underline-offset-4">
          Open the journal
        </Link>
      </div>
    </div>
  )
}

function Message({
  item,
  decisions,
  chat,
}: {
  item: Item
  decisions: Map<string, Decision>
  chat: boolean
}) {
  switch (item.type) {
    case "user":
      // A report run opens with its skill invocation; a conversation with the user's words.
      return !chat && item.text.startsWith("/") ? (
        <p className="text-center text-xs text-muted-foreground">
          Started <code className="font-mono">{item.text.split("\n")[0]}</code>
        </p>
      ) : (
        <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-[0.95rem] leading-6 break-words whitespace-pre-wrap text-secondary-foreground">
          {item.text}
        </div>
      )
    case "assistant":
      return (
        <div className="text-[0.95rem] leading-7">
          <Markdown text={item.text} />
          {item.streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/60 align-middle" />}
        </div>
      )
    case "steps":
      return <Steps steps={item.steps} />
    case "decision":
      return <DecisionCard id={item.id} decisions={decisions} />
  }
}

function hostname(url: string) {
  try {
    return new URL(url).hostname || url
  } catch {
    return url
  }
}

function webLink(url: string) {
  try {
    const parsed = new URL(url)
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null
  } catch {
    return null
  }
}

/**
 * Everything the advisor looked up, in order: searches by their query, pages by hostname
 * with the full URL on hover. Closed until asked for, so it never crowds the answer.
 */
export function SitesVisited({ visits }: { visits: Visit[] }) {
  if (!visits.length) return null
  return (
    <Collapsible className="group/sites rounded-lg border bg-card text-sm">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted-foreground">
        <ChevronRight className="size-4 transition-transform group-data-[open]/sites:rotate-90" />
        <Globe className="size-3.5" />
        <span>
          Looked up on the web ({visits.length})
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="space-y-1 border-t px-3 py-2" aria-label="Sites visited">
          {visits.map((visit) => {
            const href = visit.action === "fetch" ? webLink(visit.value) : null
            return (
              <li key={visit.seq} className="flex items-start gap-2 text-xs">
                {visit.action === "search" ? (
                  <>
                    <Search className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 break-words">Searched “{visit.value}”</span>
                  </>
                ) : (
                  <>
                    <Globe className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noreferrer noopener"
                        title={visit.value}
                        className="min-w-0 break-all underline-offset-2 hover:underline"
                      >
                        {hostname(visit.value)}
                      </a>
                    ) : (
                      <span className="min-w-0 break-all" title={visit.value}>
                        {hostname(visit.value)}
                      </span>
                    )}
                  </>
                )}
              </li>
            )
          })}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** Which engine and model the run uses; the model the engine reported wins once known. */
export function RunEngine({ run, visits = 0 }: { run: Run; visits?: number }) {
  if (!run.engine) return null
  const model = run.reported_model ?? run.model
  // The live stream may be ahead of the record, which settles when the run ends.
  const count = Math.max(visits, run.web_count ?? 0)
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground" aria-label="Engine and model">
      <Badge variant="outline">{engineLabel(run.engine)}</Badge>
      {model && <code className="font-mono">{model}</code>}
      {run.effort && <span>{run.effort} effort</span>}
      <span>{LEVEL_LABELS[run.level]?.label ?? run.level}</span>
      {(run.web || count > 0) && (
        <span className="inline-flex items-center gap-1">
          <Globe className="size-3" />
          {count} web {count === 1 ? "visit" : "visits"}
        </span>
      )}
      {run.cost_usd > 0 && <span>${run.cost_usd.toFixed(2)} so far</span>}
    </p>
  )
}

function ReportCard({ run }: { run: Run }) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-success/30 bg-success/5 p-3 text-sm">
      <CircleCheck className="size-4 text-success-foreground" />
      <span className="flex-1">The report is saved and verified.</span>
      <Button variant="outline" size="sm" render={<Link to={reportHref(run.report)} />}>
        <FileText /> Open report
      </Button>
    </div>
  )
}

/** How a report run ended. */
function Outcome({ run, onResume, onNew }: { run: Run; onResume: () => void; onNew: () => void }) {
  switch (run.status) {
    case "completed":
      return <ReportCard run={run} />
    case "partial":
      return (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm">
          <CircleAlert className="size-4 text-warning-foreground" />
          <span className="flex-1">
            The run stopped before its report verified. Decisions it recorded are kept; resuming continues the same report.
          </span>
          <Button size="sm" onClick={onResume}>
            <Play /> Resume
          </Button>
        </div>
      )
    case "failed":
      return <Failure run={run} onNew={onNew} />
    case "awaiting_input":
      return <p className="text-sm text-muted-foreground">The advisor is waiting for your reply.</p>
    case "cancelled":
      return <p className="text-sm text-muted-foreground">Stopped. Send a message to continue.</p>
    default:
      return null
  }
}

function Failure({ run, onNew }: { run: Run; onNew: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
      <CircleX className="size-4 text-destructive-foreground" />
      <span className="flex-1">
        {run.error?.message ?? "The advisor stopped with an error."}
        {run.session_id ? " Send a message to try again." : ""}
      </span>
      {!run.session_id && (
        <Button variant="outline" size="sm" onClick={onNew}>
          New chat
        </Button>
      )}
    </div>
  )
}

/** How the latest turn of a conversation ended; a plain answer needs no note. */
function TurnOutcome({ run, onNew }: { run: Run; onNew: () => void }) {
  if (run.status === "failed") return <Failure run={run} onNew={onNew} />
  if (run.status === "cancelled") {
    return <p className="text-sm text-muted-foreground">Stopped. Send a message to continue.</p>
  }
  if (run.report && run.verify?.valid) return <ReportCard run={run} />
  return null
}

/** The conversation so far: messages, the advisor's steps, sites visited, and how it stands. */
export function RunView({
  run,
  transcript,
  decisions,
  pending,
  onResume,
  onNew,
}: {
  run: Run | undefined
  transcript: Transcript
  decisions: Decision[]
  /** A message just sent, shown until the stream echoes it. */
  pending?: string
  onResume: () => void
  onNew: () => void
}) {
  const end = React.useRef<HTMLDivElement>(null)
  const follow = React.useRef(true)
  const chat = run?.mode === "chat"
  const status = transcript.status ?? run?.status
  const active = status !== undefined && ACTIVE.includes(status)
  const known = new Map(decisions.map((d) => [d.id, d]))
  const streaming = transcript.items.some((item) => item.type === "assistant" && item.streaming)

  // Follow new text only while the reader is at the bottom; scrolling up to read stops it.
  React.useEffect(() => {
    const onScroll = () => {
      const page = document.documentElement
      follow.current = page.scrollHeight - window.scrollY - window.innerHeight < 200
    }
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])
  React.useEffect(() => {
    if (follow.current) end.current?.scrollIntoView?.({ block: "end" })
  }, [transcript.last, pending])

  return (
    <div className="space-y-5" aria-live="polite">
      {transcript.items.map((item) => (
        <Message key={`${item.type}-${item.seq}`} item={item} decisions={known} chat={chat || !run} />
      ))}
      {pending && !transcript.items.length && (
        <Message item={{ type: "user", seq: 0, text: pending }} decisions={known} chat />
      )}
      {(active || (pending && !transcript.items.length)) && !streaming && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="size-4 animate-spin" />
          {status === "verifying" ? "Checking the report…" : "Thinking…"}
        </p>
      )}
      <SitesVisited visits={transcript.web} />
      {!active && run && transcript.status && (chat ? <TurnOutcome run={run} onNew={onNew} /> : <Outcome run={run} onResume={onResume} onNew={onNew} />)}
      {transcript.denied > 0 && !active && (
        <p className="text-xs text-muted-foreground">
          {transcript.denied} tool {transcript.denied === 1 ? "call was" : "calls were"} refused by the advisor's limits.
        </p>
      )}
      {/* The margin keeps the last line clear of the message box pinned below. */}
      <div ref={end} className="scroll-mb-56" />
    </div>
  )
}
