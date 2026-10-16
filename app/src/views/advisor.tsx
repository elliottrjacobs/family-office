import { Check, FileText, MessageSquare, Terminal } from "lucide-react"

import { levels, reports } from "@/api/office"
import { useApi } from "@/api/use-api"
import { useAppData } from "@/app-data"
import { AdvisorIcon, advisorName, GROUP_LABELS } from "@/components/advisor-icon"
import { CommandLine } from "@/components/command-line"
import { Empty, Loading, Page } from "@/components/page"
import { Badge } from "@/components/ui/badge"
import { day } from "@/lib/format"
import { Link, reportHref } from "@/lib/router"

const TIERS = { fast: "Fast model", balanced: "Balanced model", strong: "Strongest model" }

export function AdvisorPage({ name }: { name: string }) {
  const { registry } = useAppData()
  const table = useApi("levels", levels)
  const library = useApi("reports", reports, 60_000)
  if (!registry) return <Page><Loading /></Page>
  const advisor = registry.skills.find((a) => a.name === name)
  if (!advisor) {
    return (
      <Page>
        <Empty icon={MessageSquare} title="No such advisor">
          <Link to="/" className="underline underline-offset-4">Back to Home</Link>
        </Empty>
      </Page>
    )
  }
  const reads = table.data?.[advisor.default_context]
  const recent = (library.data?.reports ?? [])
    .filter((r) => r.frontmatter.kind === advisor.report_kind)
    .sort((a, b) => (a.frontmatter.date < b.frontmatter.date ? 1 : -1))
    .slice(0, 5)
  const invocation = `/${advisor.name}${advisor.args.includes("<subject>") ? " <subject>" : ""}`
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
        <div className="space-y-4">
          <section className="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <MessageSquare className="size-4 text-muted-foreground" /> Ask {advisorName(advisor.name)}
            </h2>
            <p className="text-sm text-muted-foreground">
              Chat in this page arrives in the next release. Until then, start the advisor from
              your coding agent in the office folder:
            </p>
            <CommandLine command={invocation} />
            {advisor.args.includes("--deep") && (
              <p className="text-xs text-muted-foreground">Add --deep for the five-analyst evidence pass.</p>
            )}
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
        <aside className="space-y-4 rounded-xl border bg-card p-4 sm:p-5">
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
