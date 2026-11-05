import * as React from "react"
import { CircleAlert, FileText, Loader2, Play } from "lucide-react"

import { ApiError } from "@/api/client"
import type { Advisor, Level } from "@/api/office"
import {
  type Effort,
  type EngineChoice,
  type EngineStatus,
  engineLabel,
  launch,
  type ModelCatalog,
  models,
  preview,
  type Run,
} from "@/api/runs"
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
const EFFORTS: Effort[] = ["low", "medium", "high"]
const OTHER = "__other__"
const STORAGE = "fo.launch.v1."

function remembered(advisor: string): EngineChoice | undefined {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(STORAGE + advisor) ?? "null") as EngineChoice | null
    if (value && typeof value.engine === "string" && typeof value.model === "string" && EFFORTS.includes(value.effort)) {
      return value
    }
  } catch {
    // Unreadable or blocked storage falls back to the office defaults.
  }
  return undefined
}

function remember(advisor: string, choice: EngineChoice) {
  try {
    window.sessionStorage.setItem(STORAGE + advisor, JSON.stringify(choice))
  } catch {
    // The choice is a convenience; losing it is harmless.
  }
}

/** The office default for an engine, then the curated recommendation, then the first entry. */
function defaultsFor(engine: string, catalog: ModelCatalog | undefined, engines: EngineStatus[]): EngineChoice {
  const office = catalog?.defaults[engine] ?? engines.find((e) => e.name === engine)?.defaults
  const curated = catalog?.engines[engine]?.models ?? []
  const recommended = curated.find((m) => m.recommended) ?? curated[0]
  return { engine, model: office?.model ?? recommended?.id ?? "", effort: office?.effort ?? "high" }
}

function initialChoice(
  advisor: string,
  catalog: ModelCatalog | undefined,
  engines: EngineStatus[],
  officeDefault: string | undefined
): EngineChoice | undefined {
  const usable = engines.filter((e) => e.usable).map((e) => e.name)
  if (!usable.length) return undefined
  const stored = remembered(advisor)
  if (stored && usable.includes(stored.engine)) return stored
  const preferred = catalog?.default ?? officeDefault
  return defaultsFor(preferred && usable.includes(preferred) ? preferred : usable[0], catalog, engines)
}

/** Engine, model, and effort for this run; unusable engines show why and cannot be chosen. */
function EngineFields({
  choice,
  catalog,
  engines,
  onChange,
}: {
  choice: EngineChoice
  catalog: ModelCatalog | undefined
  engines: EngineStatus[]
  onChange: (choice: EngineChoice) => void
}) {
  const curated = catalog?.engines[choice.engine]?.models ?? []
  const listed = curated.some((m) => m.id === choice.model)
  const [other, setOther] = React.useState(!listed && choice.model !== "")
  const custom = other || (!listed && choice.model !== "")
  const efforts = catalog?.engines[choice.engine]?.efforts ?? EFFORTS
  const blocked = engines.filter((e) => !e.usable && e.message)
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[auto_1fr_auto]">
        <div className="space-y-1.5">
          <p className="text-sm font-medium">Engine</p>
          <Segmented
            label="Engine"
            options={engines.map((e) => ({
              value: e.name,
              label: catalog?.engines[e.name]?.label ?? engineLabel(e.name),
              disabled: !e.usable,
              title: e.usable ? undefined : (e.message ?? undefined),
            }))}
            value={choice.engine}
            onChange={(engine) => {
              setOther(false)
              onChange(defaultsFor(engine, catalog, engines))
            }}
          />
        </div>
        <div className="min-w-0 space-y-1.5">
          <label htmlFor="run-model" className="text-sm font-medium">
            Model
          </label>
          <select
            id="run-model"
            value={custom ? OTHER : choice.model}
            onChange={(event) => {
              const value = event.target.value
              if (value === OTHER) {
                setOther(true)
                onChange({ ...choice, model: "" })
              } else {
                setOther(false)
                onChange({ ...choice, model: value })
              }
            }}
            className="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          >
            {curated.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
                {m.recommended ? " (recommended)" : ""}
              </option>
            ))}
            <option value={OTHER}>Other…</option>
          </select>
          {custom && (
            <Input
              aria-label="Model id"
              value={choice.model}
              onChange={(event) => onChange({ ...choice, model: event.target.value.trim() })}
              placeholder="Model id, as the engine names it"
              autoComplete="off"
              spellCheck={false}
            />
          )}
        </div>
        <div className="space-y-1.5">
          <p className="text-sm font-medium">Effort</p>
          <Segmented
            label="Effort"
            options={efforts.map((value) => ({ value, label: titleCase(value) }))}
            value={choice.effort}
            onChange={(effort) => onChange({ ...choice, effort })}
          />
        </div>
      </div>
      {blocked.map((e) => (
        <p key={e.name} className="text-xs text-muted-foreground">
          {catalog?.engines[e.name]?.label ?? engineLabel(e.name)} is unavailable: {e.message}
        </p>
      ))}
    </div>
  )
}

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
  engines = [],
  officeDefault,
  onLaunched,
}: {
  advisor: Advisor
  deepAvailable: boolean
  engines?: EngineStatus[]
  officeDefault?: string
  onLaunched: (run: Run) => void
}) {
  const catalog = useApi("models", models)
  // Null until the user picks something; until then the office defaults apply.
  const [picked, setPicked] = React.useState<EngineChoice | null>(null)
  const choice = picked ?? initialChoice(advisor.name, catalog.data, engines, officeDefault)
  const choose = (next: EngineChoice) => {
    setPicked(next)
    remember(advisor.name, next)
  }
  const household = advisor.group === "household" || advisor.group === "routine"
  const [subject, setSubject] = React.useState(household ? "household" : "")
  const [level, setLevel] = React.useState<Level>(advisor.default_context)
  const [deep, setDeep] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string>()
  const settled = useDebounced(subject)
  const subjectValid = SUBJECT.test(subject.trim())
  const valid = subjectValid && (!choice || choice.model.trim() !== "")
  const canDeep = advisor.deep && deepAvailable

  const start = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!valid) return
    setBusy(true)
    setError(undefined)
    try {
      onLaunched(await launch(advisor.name, normalize(subject), level, canDeep && deep, choice))
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
            aria-invalid={subject !== "" && !subjectValid}
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
      {/* The fields wait for the curated list so an office model shows as listed or as Other. */}
      {choice && catalog.data && (
        <EngineFields
          key={choice.engine}
          choice={choice}
          catalog={catalog.data}
          engines={engines}
          onChange={choose}
        />
      )}
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
      {subjectValid && SUBJECT.test(settled.trim()) && <Preview advisor={advisor} subject={normalize(settled)} level={level} />}
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
