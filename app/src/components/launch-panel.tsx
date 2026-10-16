import * as React from "react"
import { CircleAlert, FileText, Loader2, Play } from "lucide-react"

import { ApiError } from "@/api/client"
import type { Advisor, Level } from "@/api/office"
import { launch, preview, type Run } from "@/api/runs"
import { useApi } from "@/api/use-api"
import { advisorName } from "@/components/advisor-icon"
import { message } from "@/components/confirm-dialog"
import { Segmented } from "@/components/segmented"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { titleCase } from "@/lib/format"
import { Link, reportHref } from "@/lib/router"

const SUBJECT = /^[A-Za-z0-9][A-Za-z0-9._-]*$/

function useDebounced<T>(value: T, delay = 400) {
  const [settled, setSettled] = React.useState(value)
  React.useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return settled
}

function normalize(subject: string) {
  const trimmed = subject.trim()
  return trimmed.toLowerCase() === "household" ? "household" : trimmed.toUpperCase()
}

/** What the advisor will read at this level, from the same start call the run makes. */
function Preview({ advisor, subject, level }: { advisor: Advisor; subject: string; level: Level }) {
  const loaded = useApi(`preview:${advisor.name}:${subject}:${level}`, () => preview(advisor.name, subject, level))
  if (loaded.loading) {
    return <p className="text-xs text-muted-foreground">Checking what {advisorName(advisor.name)} will read…</p>
  }
  if (loaded.error) return <p className="text-xs text-destructive-foreground">{loaded.error.message}</p>
  const data = loaded.data!
  const brief = data.brief.data
  const prior = data.prior.data
  return (
    <div className="space-y-2 rounded-lg bg-muted/50 p-3 text-xs">
      <p className="font-medium">
        What {advisorName(advisor.name)} will read
        {brief && <span className="ml-1 font-normal text-muted-foreground">(about {brief.estimated_tokens} tokens of brief)</span>}
      </p>
      {brief ? (
        <ul className="space-y-1 text-muted-foreground">
          <li>
            {brief.corrections.length} standing {brief.corrections.length === 1 ? "correction" : "corrections"}
            {brief.corrections.length > 0 && `: ${brief.corrections.map((c) => c.text).join("; ").slice(0, 160)}`}
          </li>
          <li>
            {brief.decisions.length} open {brief.decisions.length === 1 ? "decision" : "decisions"}
            {brief.decisions.length > 0 && `: ${brief.decisions.map((d) => `${titleCase(d.action.toLowerCase())} ${d.subject}`).join(", ")}`}
          </li>
          {brief.warnings.map((w) => (
            <li key={w} className="text-warning-foreground">
              {w}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-destructive-foreground">The brief could not be built ({data.brief.reason}).</p>
      )}
      <p className="flex flex-wrap items-center gap-1 text-muted-foreground">
        <FileText className="size-3" />
        {prior ? (
          <>
            Builds on{" "}
            <Link to={reportHref(prior.path)} className="underline underline-offset-2">
              {prior.path}
            </Link>
          </>
        ) : (
          "No prior report on this subject."
        )}
      </p>
      {data.report.data && (
        <p className="font-mono text-[0.7rem] break-all text-muted-foreground">Writes {data.report.data.path}</p>
      )}
    </div>
  )
}

export function LaunchPanel({
  advisor,
  deepAvailable,
  onLaunched,
}: {
  advisor: Advisor
  deepAvailable: boolean
  onLaunched: (run: Run) => void
}) {
  const household = advisor.group === "household" || advisor.group === "routine"
  const [subject, setSubject] = React.useState(household ? "household" : "")
  const [level, setLevel] = React.useState<Level>(advisor.default_context)
  const [deep, setDeep] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string>()
  const settled = useDebounced(subject)
  const valid = SUBJECT.test(subject.trim())
  const canDeep = advisor.deep && deepAvailable

  const start = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!valid) return
    setBusy(true)
    setError(undefined)
    try {
      onLaunched(await launch(advisor.name, normalize(subject), level, canDeep && deep))
    } catch (reason) {
      setError(reason instanceof ApiError ? message(reason) : "The run could not start.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={start} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <div className="space-y-1.5">
          <label htmlFor="run-subject" className="text-sm font-medium">
            Subject
          </label>
          <Input
            id="run-subject"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder={household ? "household" : "Ticker, such as ACME"}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={subject !== "" && !valid}
          />
        </div>
        <div className="space-y-1.5">
          <p className="text-sm font-medium">Context level</p>
          <Segmented
            label="Context level"
            options={advisor.allowed_context.map((value) => ({ value, label: titleCase(value) }))}
            value={level}
            onChange={setLevel}
          />
        </div>
      </div>
      {canDeep && (
        <label className="flex items-center gap-3 text-sm">
          <Switch checked={deep} onCheckedChange={setDeep} aria-label="Deep mode" />
          <span>
            Deep mode
            <span className="block text-xs text-muted-foreground">
              Five analysts gather evidence first; slower and costlier.
            </span>
          </span>
        </label>
      )}
      {valid && SUBJECT.test(settled.trim()) && <Preview advisor={advisor} subject={normalize(settled)} level={level} />}
      {error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive-foreground">
          <CircleAlert className="mt-0.5 size-4 shrink-0" />
          {error}
        </p>
      )}
      <Button type="submit" disabled={!valid || busy}>
        {busy ? <Loader2 className="animate-spin" /> : <Play />} Start {advisorName(advisor.name)}
      </Button>
    </form>
  )
}
