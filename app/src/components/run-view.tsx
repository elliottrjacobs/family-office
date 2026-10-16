import * as React from "react"
import {
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  FileText,
  Loader2,
  Play,
  Scale,
  Send,
  Square,
} from "lucide-react"

import type { Decision } from "@/api/office"
import { ACTIVE, type Run } from "@/api/runs"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { action as actionLabel } from "@/lib/format"
import { Markdown } from "@/lib/markdown"
import { Link, reportHref } from "@/lib/router"
import type { Item, Step, Transcript } from "@/lib/transcript"

function Steps({ steps }: { steps: Step[] }) {
  const failed = steps.filter((s) => s.ok === false).length
  return (
    <Collapsible className="group/steps rounded-lg border bg-card text-sm">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted-foreground">
        <ChevronRight className="size-4 transition-transform group-data-[open]/steps:rotate-90" />
        <span>
          Ran {steps.length} {steps.length === 1 ? "step" : "steps"}
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

function Message({ item, decisions }: { item: Item; decisions: Map<string, Decision> }) {
  switch (item.type) {
    case "user":
      return item.text.startsWith("/") ? (
        <p className="text-center text-xs text-muted-foreground">
          Started <code className="font-mono">{item.text.split("\n")[0]}</code>
        </p>
      ) : (
        <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm whitespace-pre-wrap text-primary-foreground">
          {item.text}
        </div>
      )
    case "assistant":
      return (
        <div className="text-sm">
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

function Outcome({ run, onResume, onNew }: { run: Run; onResume: () => void; onNew: () => void }) {
  const cost = run.cost_usd ? ` Cost so far $${run.cost_usd.toFixed(2)}.` : ""
  switch (run.status) {
    case "completed":
      return (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-success/30 bg-success/5 p-3 text-sm">
          <CircleCheck className="size-4 text-success-foreground" />
          <span className="flex-1">The report verified.{cost}</span>
          <Button variant="outline" size="sm" render={<Link to={reportHref(run.report)} />}>
            <FileText /> Open report
          </Button>
        </div>
      )
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
      return (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <CircleX className="size-4 text-destructive-foreground" />
          <span className="flex-1">{run.error?.message ?? "The run failed."}{cost}</span>
          <Button variant="outline" size="sm" onClick={onNew}>
            Start over
          </Button>
        </div>
      )
    case "awaiting_input":
      return <p className="text-sm text-muted-foreground">The advisor is waiting for your reply.{cost}</p>
    case "cancelled":
      return <p className="text-sm text-muted-foreground">Cancelled. Send a message to continue the same session.</p>
    default:
      return null
  }
}

export function RunView({
  run,
  transcript,
  decisions,
  onReply,
  onCancel,
  onNew,
}: {
  run: Run | undefined
  transcript: Transcript
  decisions: Decision[]
  onReply: (text: string) => Promise<void>
  onCancel: () => Promise<void>
  onNew: () => void
}) {
  const [text, setText] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const end = React.useRef<HTMLDivElement>(null)
  const status = transcript.status ?? run?.status
  const active = status !== undefined && ACTIVE.includes(status)
  const known = new Map(decisions.map((d) => [d.id, d]))

  React.useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" })
  }, [transcript.last])

  const send = async (words: string) => {
    setBusy(true)
    try {
      await onReply(words)
      setText("")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-3" aria-live="polite">
        {transcript.items.map((item) => (
          <Message key={`${item.type}-${item.seq}`} item={item} decisions={known} />
        ))}
        {active && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {status === "verifying" ? "Checking the report…" : "Working…"}
            <Button variant="ghost" size="sm" className="ml-auto" onClick={onCancel}>
              <Square /> Cancel
            </Button>
          </div>
        )}
        {!active && run && transcript.status && <Outcome run={run} onResume={() => send("")} onNew={onNew} />}
        {transcript.denied > 0 && !active && (
          <p className="text-xs text-muted-foreground">
            {transcript.denied} tool {transcript.denied === 1 ? "call was" : "calls were"} refused by the run's limits.
          </p>
        )}
        <div ref={end} />
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (text.trim()) void send(text.trim())
        }}
        className="flex items-end gap-2 rounded-xl border bg-card p-2"
      >
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && text.trim()) {
              event.preventDefault()
              void send(text.trim())
            }
          }}
          placeholder={active ? "Wait for the advisor to finish" : "Reply or ask a follow-up"}
          disabled={active || busy || !run?.session_id}
          aria-label="Message"
          rows={2}
          className="min-h-0 resize-none border-0 shadow-none focus-visible:ring-0"
        />
        <Button type="submit" size="icon" disabled={active || busy || !text.trim()} aria-label="Send">
          {busy ? <Loader2 className="animate-spin" /> : <Send />}
        </Button>
      </form>
    </div>
  )
}
