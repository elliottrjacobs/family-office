import * as React from "react"
import { CalendarClock, NotebookPen, Plus, RotateCcw } from "lucide-react"

import {
  close,
  type Conviction,
  correct,
  judge,
  type Outcome,
  record,
  reopen,
  retire,
} from "@/api/actions"
import type { Correction, Decision, Level } from "@/api/office"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { Segmented } from "@/components/segmented"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { action as actionLabel } from "@/lib/format"

const OUTCOMES: { value: Outcome; label: string }[] = [
  { value: "hit", label: "Hit" },
  { value: "miss", label: "Miss" },
  { value: "neutral", label: "Neutral" },
  { value: "unknown", label: "Unknown" },
]

function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string
  label: string
  error?: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-destructive-foreground">{error}</p>
      ) : (
        hint && <p className="text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  )
}

function name(decision: Decision) {
  return `${actionLabel(decision.action)} ${decision.subject}`
}

/** Verdict buttons for an open decision; closing is undone with reopen. */
export function Verdict({ decision, onDone }: { decision: Decision; onDone: () => void }) {
  const [outcome, setOutcome] = React.useState<Outcome | null>(null)
  const [note, setNote] = React.useState("")
  return (
    <>
      <div className="flex flex-wrap items-center gap-1">
        <span className="mr-1 text-xs text-muted-foreground">Verdict</span>
        {OUTCOMES.map((o) => (
          <Button key={o.value} variant="outline" size="xs" onClick={() => setOutcome(o.value)}>
            {o.label}
          </Button>
        ))}
      </div>
      <ConfirmDialog
        open={outcome !== null}
        onOpenChange={(open) => {
          if (!open) {
            setOutcome(null)
            setNote("")
          }
        }}
        title={`Close ${name(decision)} as a ${outcome ?? ""}?`}
        description={decision.thesis}
        rollback="Closing is reversible: reopen it with a reason and it returns to the open list."
        confirm={`Close as ${outcome ?? ""}`}
        onConfirm={async () => {
          await close(decision.id, outcome!, note)
          onDone()
        }}
      >
        <Field id={`note-${decision.id}`} label="Note (optional)">
          <Textarea
            id={`note-${decision.id}`}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="What happened"
            rows={2}
          />
        </Field>
      </ConfirmDialog>
    </>
  )
}

export function Reopen({ decision, onDone }: { decision: Decision; onDone: () => void }) {
  const [open, setOpen] = React.useState(false)
  const [reason, setReason] = React.useState("")
  return (
    <>
      <Button variant="outline" size="xs" onClick={() => setOpen(true)}>
        <RotateCcw /> Reopen
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (!next) setReason("")
        }}
        title={`Reopen ${name(decision)}?`}
        rollback="Reopening is reversible: close it again with a verdict."
        confirm="Reopen decision"
        disabled={!reason.trim()}
        onConfirm={async () => {
          await reopen(decision.id, reason.trim())
          onDone()
        }}
      >
        <Field id={`reason-${decision.id}`} label="Reason">
          <Textarea
            id={`reason-${decision.id}`}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="What changed"
            rows={2}
          />
        </Field>
      </ConfirmDialog>
    </>
  )
}

function inWeeks(weeks: number) {
  const date = new Date()
  date.setDate(date.getDate() + weeks * 7)
  return date.toISOString().slice(0, 10)
}

/** Defer judgment: the review stops asking until the date. */
export function Defer({ decision, onDone }: { decision: Decision; onDone: () => void }) {
  const [open, setOpen] = React.useState(false)
  const [until, setUntil] = React.useState(inWeeks(4))
  const [note, setNote] = React.useState("")
  return (
    <>
      <Button variant="ghost" size="xs" onClick={() => setOpen(true)}>
        <CalendarClock /> Defer
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Defer judgment on ${name(decision)}?`}
        rollback="The weekly review asks again after this date; defer again or give a verdict any time."
        confirm="Defer judgment"
        disabled={!/^\d{4}-\d{2}-\d{2}$/.test(until)}
        onConfirm={async () => {
          await judge(decision.id, until, note)
          onDone()
        }}
      >
        <Field id={`until-${decision.id}`} label="Judge again after">
          <Input id={`until-${decision.id}`} type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
        </Field>
        <Field id={`judge-note-${decision.id}`} label="Note (optional)">
          <Textarea id={`judge-note-${decision.id}`} value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
        </Field>
      </ConfirmDialog>
    </>
  )
}

const CONVICTIONS: { value: Conviction; label: string }[] = [
  { value: "HIGH", label: "High" },
  { value: "MEDIUM", label: "Medium" },
  { value: "LOW", label: "Low" },
]
const LEVELS: { value: Level; label: string }[] = [
  { value: "none", label: "None" },
  { value: "household", label: "Household" },
  { value: "full", label: "Full" },
]

interface Draft {
  subject: string
  action: string
  thesis: string
  invalidate: string
  conviction: Conviction | null
  context_level: Level
  conditions: string
}

const BLANK: Draft = {
  subject: "",
  action: "",
  thesis: "",
  invalidate: "",
  conviction: null,
  context_level: "none",
  conditions: "",
}

/** The record-decision form; it replaces the journal skill in the browser. */
export function RecordDecision({ onDone, report }: { onDone: () => void; report?: string }) {
  const [open, setOpen] = React.useState(false)
  const [draft, setDraft] = React.useState<Draft>(BLANK)
  const [errors, setErrors] = React.useState<Partial<Record<keyof Draft, string>>>({})
  const set = (key: keyof Draft) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setDraft({ ...draft, [key]: event.target.value })

  const validate = () => {
    const found: Partial<Record<keyof Draft, string>> = {}
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(draft.subject.trim())) found.subject = "Subject is required: a ticker or household."
    if (!draft.action.trim()) found.action = "Action is required, such as HOLD or TRIM."
    if (!draft.thesis.trim()) found.thesis = "Thesis is required."
    if (!draft.invalidate.trim()) found.invalidate = "Invalidation is required: what would prove it wrong."
    if (!draft.conviction) found.conviction = "Conviction is required."
    setErrors(found)
    return Object.keys(found).length === 0
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        <NotebookPen /> Record a decision
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (!next) {
            setDraft(BLANK)
            setErrors({})
          }
        }}
        title="Record a decision"
        description="Recorded with the same fields an advisor uses, tagged as from the web app."
        rollback="Decisions are never deleted; close it with a verdict, and reopen it if that was wrong."
        confirm="Record decision"
        onConfirm={async () => {
          if (!validate()) return false
          const subject = draft.subject.trim()
          await record({
            subject: subject.toLowerCase() === "household" ? "household" : subject.toUpperCase(),
            action: draft.action.trim(),
            thesis: draft.thesis.trim(),
            invalidate: draft.invalidate.trim(),
            conviction: draft.conviction!,
            context_level: draft.context_level,
            when: draft.conditions.split("\n").map((l) => l.trim()).filter(Boolean),
            ...(report ? { report } : {}),
          })
          onDone()
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id="d-subject" label="Subject" error={errors.subject}>
            <Input id="d-subject" value={draft.subject} onChange={set("subject")} placeholder="ACME" />
          </Field>
          <Field id="d-action" label="Action" error={errors.action}>
            <Input id="d-action" value={draft.action} onChange={set("action")} placeholder="HOLD" />
          </Field>
        </div>
        <Field id="d-thesis" label="Thesis" error={errors.thesis}>
          <Textarea id="d-thesis" value={draft.thesis} onChange={set("thesis")} rows={3} />
        </Field>
        <Field id="d-invalidate" label="Invalidate if" error={errors.invalidate}>
          <Textarea id="d-invalidate" value={draft.invalidate} onChange={set("invalidate")} rows={2} />
        </Field>
        <Field
          id="d-when"
          label="Conditions (optional)"
          hint="One per line, such as price < 100 or gross_margin < 0.38 for 2q."
        >
          <Textarea id="d-when" value={draft.conditions} onChange={set("conditions")} rows={2} className="font-mono text-xs" />
        </Field>
        <div className="flex flex-wrap gap-4">
          <div className="space-y-1.5">
            <p className="text-sm font-medium">Conviction</p>
            <Segmented
              label="Conviction"
              options={CONVICTIONS}
              value={draft.conviction}
              onChange={(conviction) => setDraft({ ...draft, conviction })}
              invalid={Boolean(errors.conviction)}
            />
            {errors.conviction && <p className="text-xs text-destructive-foreground">{errors.conviction}</p>}
          </div>
          <div className="space-y-1.5">
            <p className="text-sm font-medium">Context it rests on</p>
            <Segmented
              label="Context level"
              options={LEVELS}
              value={draft.context_level}
              onChange={(context_level) => setDraft({ ...draft, context_level })}
            />
          </div>
        </div>
      </ConfirmDialog>
    </>
  )
}

export function AddCorrection({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = React.useState(false)
  const [text, setText] = React.useState("")
  const [scope, setScope] = React.useState("global")
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Plus /> Add correction
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (!next) {
            setText("")
            setScope("global")
          }
        }}
        title="Add a standing correction"
        description="Advisors read it in every later brief within its scope."
        rollback="Retire it any time; retired corrections stop applying but stay in the history."
        confirm="Add correction"
        disabled={!text.trim() || !/^(global|(skill|subject):[A-Za-z0-9._-]+)$/.test(scope)}
        onConfirm={async () => {
          await correct(text.trim(), scope)
          onDone()
        }}
      >
        <Field id="c-text" label="Correction">
          <Textarea id="c-text" value={text} onChange={(e) => setText(e.target.value)} rows={3} />
        </Field>
        <Field id="c-scope" label="Scope" hint="global, skill:cio, or subject:ACME">
          <Input id="c-scope" value={scope} onChange={(e) => setScope(e.target.value)} className="font-mono" />
        </Field>
      </ConfirmDialog>
    </>
  )
}

export function Retire({ correction, onDone }: { correction: Correction; onDone: () => void }) {
  const [open, setOpen] = React.useState(false)
  return (
    <>
      <Button variant="ghost" size="xs" onClick={() => setOpen(true)}>
        Retire
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Retire this correction?"
        description={correction.text}
        rollback="Retiring keeps it in the history; add it again to bring it back."
        confirm="Retire correction"
        onConfirm={async () => {
          await retire(correction.id)
          onDone()
        }}
      />
    </>
  )
}
