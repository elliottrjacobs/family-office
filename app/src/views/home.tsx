import { ChartPie, CircleCheck, Newspaper, RefreshCw, Scale } from "lucide-react"

import { allocation, decisions, netWorth, reports } from "@/api/office"
import { useApi } from "@/api/use-api"
import { needsVerdict, settingUp, useAppData } from "@/app-data"
import { AdvisorIcon, advisorName, byAdvisorOrder } from "@/components/advisor-icon"
import { Empty, ErrorNotice, Loading, Page, SectionTitle, Stat } from "@/components/page"
import { Button } from "@/components/ui/button"
import { action, age, day, money, moment } from "@/lib/format"
import { Link, reportHref } from "@/lib/router"
import { SetupCard } from "@/views/onboarding"

function greeting(now = new Date()) {
  const hour = now.getHours()
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening"
}

interface Attention {
  key: string
  icon: typeof Scale
  tone: "destructive" | "warning" | "muted"
  title: string
  detail: string
  to: string
  action: string
}

const TONES = {
  destructive: "bg-destructive/10 text-destructive-foreground",
  warning: "bg-warning/15 text-warning-foreground",
  muted: "bg-muted text-muted-foreground",
}

export function Home() {
  const { status, onboarding, review, registry } = useAppData()
  const worth = useApi("networth", netWorth, 60_000)
  const policy = useApi("allocation", allocation, 60_000)
  const journal = useApi("decisions", decisions, 60_000)
  const library = useApi("reports", reports, 60_000)
  const lastSync = status?.office?.last_sync

  const byId = new Map((journal.data ?? []).map((d) => [d.id, d]))
  const items: Attention[] = []
  for (const item of needsVerdict(review)) {
    const decision = byId.get(item.id)
    items.push({
      key: `verdict-${item.id}`,
      icon: Scale,
      tone: item.breached ? "destructive" : "warning",
      title: `${item.breached ? "Breached" : "Verdict due"}: ${decision ? action(decision.action) : "Decision"} ${item.subject}`,
      detail: item.breached
        ? "Its invalidation condition is true."
        : "The verdict window has passed.",
      to: "/decisions",
      action: "Review",
    })
  }
  for (const item of review?.decisions.filter((d) => d.needs_judgment && !d.breached && !d.due_for_verdict) ?? []) {
    const decision = byId.get(item.id)
    items.push({
      key: `judge-${item.id}`,
      icon: Scale,
      tone: "muted",
      title: `Needs judgment: ${decision ? action(decision.action) : "Decision"} ${item.subject}`,
      detail: "No machine-checkable condition settles it; an advisor or you should look.",
      to: "/decisions",
      action: "Open",
    })
  }
  for (const band of policy.data?.bands.filter((b) => b.outside_band) ?? []) {
    items.push({
      key: `band-${band.name}`,
      icon: ChartPie,
      tone: "warning",
      title: `${band.name} is outside its policy band`,
      detail: `${band.drift_points !== null ? `${Math.abs(band.drift_points).toFixed(1)} points ` : ""}${(band.drift_points ?? 0) > 0 ? "over" : "under"} the band.`,
      to: "/finances",
      action: "View",
    })
  }
  for (const account of worth.data?.stale_accounts ?? []) {
    items.push({
      key: `stale-${account}`,
      icon: RefreshCw,
      tone: "warning",
      title: `${account} is missing from the latest sync`,
      detail: "Its balance is from an earlier run.",
      to: "/finances",
      action: "View",
    })
  }
  for (const provider of worth.data?.stale_providers ?? []) {
    items.push({
      key: `provider-${provider}`,
      icon: RefreshCw,
      tone: "warning",
      title: `${provider} has not synced on schedule`,
      detail: "Run fo sync on the writer host.",
      to: "/",
      action: "Details",
    })
  }

  const briefing = (library.data?.reports ?? [])
    .filter((r) => r.frontmatter.kind === "briefing")
    .sort((a, b) => (a.frontmatter.date < b.frontmatter.date ? 1 : -1))[0]
  const today = new Date().toISOString().slice(0, 10)
  const featured = (registry?.skills ?? []).filter((a) => a.group === "household").sort(byAdvisorOrder)

  return (
    <Page>
      <div className="mb-6 space-y-1">
        <h1 className="text-3xl">{greeting()}</h1>
        <p className="text-sm text-muted-foreground">
          {lastSync
            ? `Your advisors read the office as of ${moment(lastSync.as_of)}, ${age(lastSync.as_of)}.`
            : "Your office has not synced yet."}
        </p>
      </div>

      {onboarding && (settingUp(onboarding.state) || onboarding.state === "stale") && (
        <div className="mb-6">
          <SetupCard data={onboarding} />
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          label="Net worth"
          value={worth.data ? money(worth.data.total, true) : "…"}
          detail={
            !worth.data?.groups.length
              ? "No accounts yet"
              : worth.data.missing_accounts.length
                ? `${worth.data.missing_accounts.length} accounts not reported, so the total is unknown`
                : "All registered accounts"
          }
        />
        <Stat
          label="Investable"
          value={policy.data ? money(policy.data.total, true) : "…"}
          detail="Basis for policy weights"
        />
        <Stat
          label="Outside policy"
          value={policy.data ? policy.data.bands.filter((b) => b.outside_band).length : "…"}
          detail={policy.data?.bands.length ? `of ${policy.data.bands.length} bands` : "No bands in the policy yet"}
          tone={policy.data?.bands.some((b) => b.outside_band) ? "warning" : undefined}
        />
      </div>
      {worth.error && <div className="mt-3"><ErrorNotice error={worth.error} retry={worth.reload} /></div>}

      <SectionTitle>Needs you</SectionTitle>
      {journal.loading || policy.loading ? (
        <Loading rows={2} />
      ) : items.length ? (
        <ul className="divide-y rounded-xl border bg-card">
          {items.map((item) => (
            <li key={item.key} className="flex items-center gap-3 p-3 sm:p-4">
              <span className={`flex size-8 shrink-0 items-center justify-center rounded-lg ${TONES[item.tone]}`}>
                <item.icon className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{item.title}</p>
                <p className="text-xs text-muted-foreground">{item.detail}</p>
              </div>
              <Button variant="outline" size="sm" render={<Link to={item.to} />}>
                {item.action}
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <Empty icon={CircleCheck} title="Nothing needs you right now">
          No breached or due decisions, every band is inside policy, and every account synced.
        </Empty>
      )}

      <SectionTitle
        aside={
          <Button variant="ghost" size="sm" render={<Link to="/reports" />}>
            All reports
          </Button>
        }
      >
        {briefing?.frontmatter.date === today ? "Today's briefing" : "Latest briefing"}
      </SectionTitle>
      {library.error ? (
        <ErrorNotice error={library.error} retry={library.reload} />
      ) : briefing ? (
        <Link
          to={reportHref(briefing.path)}
          className="block rounded-xl border bg-card p-4 transition-colors hover:bg-accent/50"
        >
          <p className="flex items-center gap-2 text-sm font-medium">
            <Newspaper className="size-4 text-muted-foreground" />
            Briefing, {day(briefing.frontmatter.date)}
          </p>
          <p className="mt-1 line-clamp-3 text-sm text-muted-foreground">{briefing.summary}</p>
        </Link>
      ) : (
        <Empty icon={Newspaper} title="No briefing yet">
          Ask the briefing advisor for one from your coding agent in the office folder.
        </Empty>
      )}

      {featured.length > 0 && (
        <>
          <SectionTitle>Household advisors</SectionTitle>
          <div className="grid gap-3 sm:grid-cols-2">
            {featured.map((advisor) => (
              <Link
                key={advisor.name}
                to={`/advisors/${advisor.name}`}
                className="flex items-start gap-3 rounded-xl border bg-card p-4 transition-colors hover:bg-accent/50"
              >
                <AdvisorIcon name={advisor.name} group={advisor.group} className="size-7" />
                <div className="min-w-0">
                  <p className="text-sm font-medium">{advisorName(advisor.name)}</p>
                  <p className="line-clamp-2 text-xs text-muted-foreground">{advisor.description}</p>
                </div>
              </Link>
            ))}
          </div>
        </>
      )}
    </Page>
  )
}
