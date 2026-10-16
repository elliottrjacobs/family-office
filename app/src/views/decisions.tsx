import * as React from "react"
import { BookOpen, FileText, NotebookPen, Scale } from "lucide-react"

import { corrections, type Decision, decisions, type ReviewItem } from "@/api/office"
import { useApi } from "@/api/use-api"
import { needsVerdict, useAppData } from "@/app-data"
import { AddCorrection, Defer, RecordDecision, Reopen, Retire, Verdict } from "@/components/decision-actions"
import { Empty, ErrorNotice, Loading, Page, PageTitle, SectionTitle } from "@/components/page"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { action, day, titleCase } from "@/lib/format"
import { Link, reportHref } from "@/lib/router"

const CONVICTION = { HIGH: "High conviction", MEDIUM: "Medium conviction", LOW: "Low conviction" }
const OUTCOME = {
  hit: "text-success-foreground",
  miss: "text-destructive-foreground",
  neutral: "text-muted-foreground",
  unknown: "text-muted-foreground",
}

function clause(c: Decision["when"][number]) {
  return `${c.metric} ${c.op} ${c.threshold}${c.quarters ? ` for ${c.quarters}q` : ""}`
}

function DecisionCard({
  decision,
  state,
  onChange,
}: {
  decision: Decision
  state?: ReviewItem
  onChange?: () => void
}) {
  return (
    <article className="rounded-xl border bg-card">
      <div className="space-y-3 p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-1.5">
          {state?.breached && <Badge variant="destructive">Breached</Badge>}
          {state?.due_for_verdict && !state.breached && (
            <Badge className="bg-warning/15 text-warning-foreground">Verdict due</Badge>
          )}
          {state?.needs_judgment && <Badge variant="outline">Needs judgment</Badge>}
          {decision.status === "closed" && decision.outcome && (
            <Badge variant="outline" className={OUTCOME[decision.outcome]}>
              {titleCase(decision.outcome)}
            </Badge>
          )}
          <Badge variant="secondary">{CONVICTION[decision.conviction]}</Badge>
          <Badge variant="outline" className="font-mono">
            {decision.subject}
          </Badge>
          <span className="ml-auto font-mono text-[0.7rem] text-muted-foreground">{decision.id}</span>
        </div>
        <h3 className="text-lg">
          {action(decision.action)} {decision.subject}
        </h3>
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[8rem_1fr]">
          <dt className="text-muted-foreground">Thesis</dt>
          <dd>{decision.thesis}</dd>
          <dt className="text-muted-foreground">Invalidate if</dt>
          <dd className="space-y-1">
            <p>{decision.invalidate}</p>
            {decision.when.map((c) => (
              <code key={clause(c)} className="mr-1.5 inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                {clause(c)}
              </code>
            ))}
          </dd>
          {decision.status === "closed" && decision.note && (
            <>
              <dt className="text-muted-foreground">Verdict note</dt>
              <dd>{decision.note}</dd>
            </>
          )}
          {decision.judged_until && (
            <>
              <dt className="text-muted-foreground">Judged until</dt>
              <dd>{day(decision.judged_until)}</dd>
            </>
          )}
        </dl>
      </div>
      <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t px-4 py-2.5 text-xs text-muted-foreground sm:px-5">
        <span>
          {titleCase(decision.source)}, {day(decision.date)}, {decision.context_level} context
        </span>
        {decision.report && (
          <Link to={reportHref(decision.report)} className="inline-flex items-center gap-1 underline underline-offset-4">
            <FileText className="size-3" /> Report
          </Link>
        )}
        {onChange && (
          <span className="ml-auto flex flex-wrap items-center gap-1">
            {decision.status === "open" ? (
              <>
                <Defer decision={decision} onDone={onChange} />
                <Verdict decision={decision} onDone={onChange} />
              </>
            ) : (
              <Reopen decision={decision} onDone={onChange} />
            )}
          </span>
        )}
      </footer>
    </article>
  )
}

function List({
  rows,
  states,
  empty,
  onChange,
}: {
  rows: Decision[]
  states: Map<string, ReviewItem>
  empty: string
  onChange?: () => void
}) {
  if (!rows.length) return <Empty icon={Scale} title={empty} />
  return (
    <div className="space-y-3">
      {rows.map((decision) => (
        <DecisionCard key={decision.id} decision={decision} state={states.get(decision.id)} onChange={onChange} />
      ))}
    </div>
  )
}

export function Decisions() {
  const { review, status, refresh } = useAppData()
  const journal = useApi("decisions", decisions, 30_000)
  const notes = useApi("corrections", corrections, 30_000)
  const writable = Boolean(status?.chat)
  const reloadJournal = journal.reload
  const reloadNotes = notes.reload
  const changed = React.useCallback(() => {
    reloadJournal()
    reloadNotes()
    refresh()
  }, [reloadJournal, reloadNotes, refresh])
  const onChange = writable ? changed : undefined
  const states = new Map((review?.decisions ?? []).map((d) => [d.id, d]))
  const due = new Set(needsVerdict(review).map((d) => d.id))
  const all = [...(journal.data ?? [])].sort((a, b) => (a.date < b.date ? 1 : -1))
  const open = all.filter((d) => d.status === "open")
  const closed = all.filter((d) => d.status === "closed")
  const verdict = open.filter((d) => due.has(d.id))
  return (
    <Page>
      <PageTitle
        title="Decision journal"
        description="Each accepted recommendation is recorded with its thesis and the condition that proves it wrong. Review checks them and asks for a verdict only when judgment is needed."
        actions={writable ? <RecordDecision onDone={changed} /> : undefined}
      />
      {journal.loading ? (
        <Loading />
      ) : journal.error ? (
        <ErrorNotice error={journal.error} retry={journal.reload} />
      ) : (
        <Tabs defaultValue={verdict.length ? "verdict" : "open"}>
          <TabsList className="mb-4" variant="line">
            <TabsTrigger value="verdict">
              Needs verdict
              {verdict.length > 0 && <Badge className="ml-1 bg-warning/15 text-warning-foreground">{verdict.length}</Badge>}
            </TabsTrigger>
            <TabsTrigger value="open">Open ({open.length})</TabsTrigger>
            <TabsTrigger value="closed">Closed ({closed.length})</TabsTrigger>
          </TabsList>
          <TabsContent value="verdict">
            <List rows={verdict} states={states} empty="No decision needs a verdict" onChange={onChange} />
          </TabsContent>
          <TabsContent value="open">
            <List rows={open} states={states} empty="No open decisions" onChange={onChange} />
          </TabsContent>
          <TabsContent value="closed">
            <List rows={closed} states={states} empty="No closed decisions yet" onChange={onChange} />
          </TabsContent>
        </Tabs>
      )}
      {!writable && (
        <p className="mt-4 flex items-start gap-2 text-xs text-muted-foreground">
          <NotebookPen className="mt-0.5 size-3.5 shrink-0" />
          fo serve was started with --read-only, so verdicts and new decisions are recorded with
          fo journal in a terminal.
        </p>
      )}
      <SectionTitle aside={writable ? <AddCorrection onDone={changed} /> : undefined}>
        Standing corrections
      </SectionTitle>
      {notes.error ? (
        <ErrorNotice error={notes.error} retry={notes.reload} />
      ) : notes.data?.length ? (
        <ul className="divide-y rounded-xl border bg-card">
          {notes.data.map((note) => (
            <li key={note.id} className="flex flex-col gap-1 px-4 py-3 text-sm sm:flex-row sm:items-start sm:gap-3">
              <Badge variant="outline" className="shrink-0 font-mono">
                {note.scope}
              </Badge>
              <span className="flex-1">{note.text}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                #{note.id}, {day(note.date)}
              </span>
              {writable && <Retire correction={note} onDone={changed} />}
            </li>
          ))}
        </ul>
      ) : (
        <Empty icon={BookOpen} title="No standing corrections">
          Corrections you give advisors apply to every later brief until retired.
        </Empty>
      )}
    </Page>
  )
}
