import * as React from "react"
import { ArrowLeft, FileText, Search, TriangleAlert } from "lucide-react"

import { report, reports, type ReportEntry } from "@/api/office"
import { useApi } from "@/api/use-api"
import { useAppData } from "@/app-data"
import { AdvisorIcon, advisorName } from "@/components/advisor-icon"
import { Empty, ErrorNotice, Loading, Page, PageTitle } from "@/components/page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { day, monthLabel } from "@/lib/format"
import { Markdown } from "@/lib/markdown"
import { Link, reportHref, useLocation } from "@/lib/router"

function title(entry: { frontmatter: ReportEntry["frontmatter"] }) {
  const { kind, subject } = entry.frontmatter
  return subject === "household" ? advisorName(kind) : `${advisorName(kind)}: ${subject}`
}

function useKindGroups() {
  const { registry } = useAppData()
  return new Map((registry?.skills ?? []).map((a) => [a.report_kind, a]))
}

export function Reports() {
  const library = useApi("reports", reports, 60_000)
  const advisors = useKindGroups()
  const [query, setQuery] = React.useState("")
  const [kind, setKind] = React.useState("all")
  const entries = (library.data?.reports ?? [])
    .filter((r) => kind === "all" || r.frontmatter.kind === kind)
    .filter((r) => {
      const q = query.trim().toLowerCase()
      return !q || `${title(r)} ${r.summary} ${r.path}`.toLowerCase().includes(q)
    })
    .sort((a, b) =>
      a.frontmatter.date === b.frontmatter.date
        ? b.path.localeCompare(a.path)
        : a.frontmatter.date < b.frontmatter.date
          ? 1
          : -1
    )
  const kinds = [...new Set((library.data?.reports ?? []).map((r) => r.frontmatter.kind))].sort()
  const months = new Map<string, ReportEntry[]>()
  for (const entry of entries) {
    const month = entry.frontmatter.date.slice(0, 7)
    months.set(month, [...(months.get(month) ?? []), entry])
  }
  return (
    <Page>
      <PageTitle
        title="Reports"
        description="Every report an advisor writes is kept with its sources, the prior report, and the decisions it recorded."
      />
      <div className="mb-6 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search reports"
            aria-label="Search reports"
            className="pl-8"
          />
        </div>
        <Select
          value={kind}
          onValueChange={(value) => setKind(String(value ?? "all"))}
          items={[{ value: "all", label: "All kinds" }, ...kinds.map((k) => ({ value: k, label: advisorName(k) }))]}
        >
          <SelectTrigger className="sm:w-48" aria-label="Report kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All kinds</SelectItem>
            {kinds.map((k) => (
              <SelectItem key={k} value={k}>
                {advisorName(k)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {library.loading ? (
        <Loading />
      ) : library.error ? (
        <ErrorNotice error={library.error} retry={library.reload} />
      ) : entries.length === 0 ? (
        <Empty icon={FileText} title={library.data?.reports.length ? "No report matches" : "No reports yet"}>
          {library.data?.reports.length
            ? "Try another search or kind."
            : "Reports appear here as advisors write them into reports/."}
        </Empty>
      ) : (
        <div className="space-y-6">
          {[...months.entries()].map(([month, rows]) => (
            <section key={month}>
              <h2 className="mb-2 font-sans text-xs font-medium text-muted-foreground">{monthLabel(month)}</h2>
              <ul className="divide-y rounded-xl border bg-card">
                {rows.map((entry) => {
                  const advisor = advisors.get(entry.frontmatter.kind)
                  const decisions = entry.frontmatter.decision_ids?.length ?? 0
                  return (
                    <li key={entry.path}>
                      <Link
                        to={reportHref(entry.path)}
                        className="flex gap-3 p-3 transition-colors hover:bg-accent/50 sm:p-4"
                      >
                        {advisor ? (
                          <AdvisorIcon name={advisor.name} group={advisor.group} className="size-8" />
                        ) : (
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
                            <FileText className="size-4 text-muted-foreground" />
                          </span>
                        )}
                        <div className="min-w-0 flex-1">
                          <p className="flex items-center gap-2 text-sm font-medium">
                            <span className="truncate">{title(entry)}</span>
                            {entry.frontmatter.legacy && <Badge variant="outline">Legacy</Badge>}
                          </p>
                          <p className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">{entry.summary}</p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {day(entry.frontmatter.date)}
                            {decisions > 0 && `, ${decisions} ${decisions === 1 ? "decision" : "decisions"}`}
                          </p>
                        </div>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
      {library.data?.parse_errors.length ? (
        <p className="mt-6 flex items-start gap-2 text-xs text-muted-foreground">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          {library.data.parse_errors.length} files under reports/ could not be read:{" "}
          {library.data.parse_errors.join(", ")}
        </p>
      ) : null}
    </Page>
  )
}

export function ReportReader() {
  const { query } = useLocation()
  const path = query.get("path") ?? ""
  const loaded = useApi(`report:${path}`, () => report(path))
  const meta = loaded.data?.frontmatter
  return (
    <Page className="max-w-3xl">
      <Button variant="ghost" size="sm" className="-ml-2 mb-4" render={<Link to="/reports" />}>
        <ArrowLeft /> Reports
      </Button>
      {loaded.loading ? (
        <Loading rows={4} />
      ) : loaded.error ? (
        <ErrorNotice error={loaded.error} />
      ) : loaded.data && meta ? (
        <article>
          <header className="mb-6 space-y-2 border-b pb-4">
            <p className="font-mono text-xs break-all text-muted-foreground">{loaded.data.path}</p>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="outline">{advisorName(meta.kind)}</Badge>
              <Badge variant="outline">{meta.subject}</Badge>
              <Badge variant="outline">{day(meta.date)}</Badge>
              {meta.context_level && <Badge variant="outline">{meta.context_level} context</Badge>}
              {meta.model && <Badge variant="outline">{meta.model}</Badge>}
              {(meta.playbooks ?? []).map((p) => (
                <Badge key={p} variant="secondary">
                  {p}
                </Badge>
              ))}
            </div>
            {meta.prior && (
              <p className="text-xs text-muted-foreground">
                Prior report:{" "}
                <Link to={reportHref(meta.prior)} className="underline underline-offset-4">
                  {meta.prior}
                </Link>
              </p>
            )}
          </header>
          <Markdown text={loaded.data.body} className="text-sm" />
        </article>
      ) : null}
    </Page>
  )
}
