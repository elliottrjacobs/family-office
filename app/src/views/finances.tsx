import { Goal as GoalIcon, Landmark, LineChart, Wallet } from "lucide-react"

import type { ApiError } from "@/api/client"
import {
  allocation,
  cashflow,
  goals,
  netWorth,
  positions,
  profile,
  spend,
} from "@/api/office"
import { useApi } from "@/api/use-api"
import { AllocationBar } from "@/components/allocation-bar"
import { Empty, ErrorNotice, Loading, Page, PageTitle, SectionTitle, Stat } from "@/components/page"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { age, money, monthLabel, moment, percent, quantity, UNKNOWN } from "@/lib/format"

interface RegistryAccount {
  id: string
  type?: string
  owner?: string
  role?: string
  provider: string
  institution?: string
}

function Unknown() {
  return <span className="text-muted-foreground">{UNKNOWN}</span>
}

function Money({ value }: { value: number | null }) {
  return value === null ? <Unknown /> : <span className="tabular-nums">{money(value)}</span>
}

function Failed({ error, retry }: { error?: ApiError; retry: () => void }) {
  return error ? <ErrorNotice error={error} retry={retry} /> : null
}

function Overview() {
  const worth = useApi("networth", netWorth, 60_000)
  const policy = useApi("allocation", allocation, 60_000)
  if (worth.loading || policy.loading) return <Loading />
  const p = policy.data
  const w = worth.data
  const cash = p?.bands.find((b) => b.name.toLowerCase() === "cash")
  const top = Object.entries(p?.weights ?? {})
    .sort((a, b) => (b[1] ?? -1) - (a[1] ?? -1))
    .slice(0, 8)
  return (
    <div className="space-y-6">
      <Failed error={worth.error} retry={worth.reload} />
      <Failed error={policy.error} retry={policy.reload} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Net worth"
          value={money(w?.total ?? null, true)}
          detail={w?.missing_accounts.length ? "Unknown until every account reports" : "Accounts less liabilities"}
        />
        <Stat label="Investable" value={money(p?.total ?? null, true)} detail="Investment and cash accounts" />
        <Stat label="Cash share" value={percent(cash?.weight ?? null)} detail="Of investable assets" />
        <Stat
          label="Stale"
          value={(w?.stale_accounts.length ?? 0) + (w?.stale_providers.length ?? 0)}
          detail={w?.as_of ? `Snapshot ${age(w.as_of)}` : "No snapshot yet"}
          tone={w && (w.stale_accounts.length || w.stale_providers.length) ? "warning" : undefined}
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <section className="rounded-xl border bg-card p-4 sm:p-5">
          <h2 className="text-base font-semibold">Allocation against policy</h2>
          <p className="mb-4 text-xs text-muted-foreground">
            Shaded areas are the bands in profile/ips.json.
          </p>
          {p?.bands.length ? (
            <div className="space-y-4">
              {p.bands.map((band) => (
                <AllocationBar key={band.name} name={band.name} weight={band.weight} min={band.min} max={band.max} />
              ))}
            </div>
          ) : (
            <Empty icon={LineChart} title="No policy bands yet">
              The onboard skill writes your investment policy, including its bands.
            </Empty>
          )}
          {p && (p.unclassified.length > 0 || p.unclassified_accounts.length > 0) && (
            <p className="mt-4 text-xs text-muted-foreground">
              {p.unclassified.length > 0 && <>Unclassified holdings count toward no band: {p.unclassified.join(", ")}. </>}
              {p.unclassified_accounts.length > 0 && <>Accounts without a role: {p.unclassified_accounts.join(", ")}.</>}
            </p>
          )}
        </section>
        <section className="rounded-xl border bg-card p-4 sm:p-5">
          <h2 className="text-base font-semibold">Largest holdings</h2>
          <p className="mb-3 text-xs text-muted-foreground">Share of investable assets.</p>
          {top.length ? (
            <ul className="space-y-2.5">
              {top.map(([symbol, weight]) => (
                <li key={symbol} className="flex items-center gap-3 text-sm">
                  <span className="w-16 shrink-0 font-mono text-xs">{symbol}</span>
                  <Progress value={weight === null ? 0 : weight * 100} className="flex-1" aria-label={symbol} />
                  <span className="w-14 text-right font-mono text-xs tabular-nums">{percent(weight)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No holdings in the latest snapshot.</p>
          )}
        </section>
      </div>
    </div>
  )
}

function Accounts() {
  const worth = useApi("networth", netWorth, 60_000)
  const registry = useApi("profile:accounts", () => profile("accounts"))
  if (worth.loading || registry.loading) return <Loading />
  const rows = new Map(
    ((registry.data?.data as { accounts?: RegistryAccount[] } | null)?.accounts ?? []).map((a) => [a.id, a])
  )
  const stale = new Set(worth.data?.stale_accounts ?? [])
  const missing = new Set(worth.data?.missing_accounts ?? [])
  return (
    <div className="space-y-3">
      <Failed error={worth.error} retry={worth.reload} />
      {worth.data?.groups.length ? (
        <div className="rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Account</TableHead>
                <TableHead className="hidden sm:table-cell">Type</TableHead>
                <TableHead className="hidden md:table-cell">Owner</TableHead>
                <TableHead className="hidden md:table-cell">Provider</TableHead>
                <TableHead className="text-right">Value</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {worth.data.groups.map((group) => {
                const account = rows.get(group.name)
                return (
                  <TableRow key={group.name}>
                    <TableCell className="font-medium">{group.name}</TableCell>
                    <TableCell className="hidden sm:table-cell">{account?.type ?? <Unknown />}</TableCell>
                    <TableCell className="hidden md:table-cell">{account?.owner ?? <Unknown />}</TableCell>
                    <TableCell className="hidden md:table-cell">{account?.provider ?? <Unknown />}</TableCell>
                    <TableCell className="text-right">
                      <Money value={group.value} />
                    </TableCell>
                    <TableCell className="text-right">
                      {missing.has(group.name) ? (
                        <Badge variant="destructive">Not reported</Badge>
                      ) : stale.has(group.name) ? (
                        <Badge className="bg-warning/15 text-warning-foreground">Stale</Badge>
                      ) : (
                        <Badge variant="outline">Current</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      ) : (
        <Empty icon={Landmark} title="No accounts yet">
          Connect a provider or register CSV accounts, then sync.
        </Empty>
      )}
    </div>
  )
}

function Holdings() {
  const held = useApi("positions", positions, 60_000)
  const policy = useApi("allocation", allocation, 60_000)
  if (held.loading) return <Loading />
  const weights = policy.data?.weights ?? {}
  return (
    <div className="space-y-3">
      <Failed error={held.error} retry={held.reload} />
      {held.data?.positions.length ? (
        <div className="rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead className="hidden sm:table-cell">Account</TableHead>
                <TableHead className="hidden md:table-cell text-right">Quantity</TableHead>
                <TableHead className="hidden md:table-cell text-right">Price</TableHead>
                <TableHead className="text-right">Value</TableHead>
                <TableHead className="text-right">Weight</TableHead>
                <TableHead className="hidden lg:table-cell text-right">Cost basis</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {held.data.positions.map((p) => (
                <TableRow key={`${p.account_id}-${p.symbol}-${p.acquired_at ?? ""}`}>
                  <TableCell className="font-mono text-xs">{p.symbol}</TableCell>
                  <TableCell className="hidden sm:table-cell">{p.account_id}</TableCell>
                  <TableCell className="hidden md:table-cell text-right tabular-nums">{quantity(p.qty)}</TableCell>
                  <TableCell className="hidden md:table-cell text-right">
                    <Money value={p.price} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money value={p.value} />
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {percent(weights[p.symbol] ?? null)}
                  </TableCell>
                  <TableCell className="hidden lg:table-cell text-right">
                    <Money value={p.cost_basis} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <Empty icon={Wallet} title="No holdings in the latest snapshot" />
      )}
      <p className="text-xs text-muted-foreground">
        {held.data?.as_of ? `Positions as of ${moment(held.data.as_of)}. ` : ""}A basis the provider
        did not report stays unknown; it is never assumed.
      </p>
    </div>
  )
}

function Cashflow() {
  const month = new Date().toISOString().slice(0, 7)
  const flow = useApi("cashflow", () => cashflow(6), 60_000)
  const current = useApi(`spend:${month}`, () => spend(month), 60_000)
  if (flow.loading) return <Loading />
  const categories = Object.entries(current.data?.categories ?? {})
    .filter(([, value]) => value !== null && value !== 0)
    .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
  return (
    <div className="space-y-6">
      <Failed error={flow.error} retry={flow.reload} />
      <div className="rounded-xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Month</TableHead>
              <TableHead className="text-right">Income</TableHead>
              <TableHead className="text-right">Spending</TableHead>
              <TableHead className="text-right">Net</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(flow.data?.months ?? []).map((m) => (
              <TableRow key={m.month}>
                <TableCell>{monthLabel(m.month)}</TableCell>
                <TableCell className="text-right">
                  <Money value={m.income} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={m.spend} />
                </TableCell>
                <TableCell
                  className={`text-right ${m.net !== null && m.net < 0 ? "text-destructive-foreground" : ""}`}
                >
                  <Money value={m.net} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <section>
        <SectionTitle>Spending by category, {monthLabel(month)}</SectionTitle>
        {categories.length ? (
          <ul className="divide-y rounded-xl border bg-card">
            {categories.map(([name, value]) => (
              <li key={name} className="flex items-center justify-between px-4 py-2.5 text-sm">
                <span>{name}</span>
                <Money value={value} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No categorized spending this month yet.</p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          Trades, dividends, and transfers are portfolio activity and are left out.
        </p>
      </section>
    </div>
  )
}

const GOAL_STATUS = {
  on_track: <Badge variant="outline" className="text-success-foreground">On track</Badge>,
  behind: <Badge className="bg-warning/15 text-warning-foreground">Behind</Badge>,
  unknown: <Badge variant="outline">Unknown</Badge>,
}

function Goals() {
  const plan = useApi("goals", goals, 60_000)
  if (plan.loading) return <Loading />
  return (
    <div className="space-y-3">
      <Failed error={plan.error} retry={plan.reload} />
      {plan.data?.goals.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {plan.data.goals.map((goal) => (
            <section key={goal.name} className="space-y-3 rounded-xl border bg-card p-4">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-sans text-sm font-semibold">{goal.name}</h3>
                {GOAL_STATUS[goal.status]}
              </div>
              <Progress
                value={goal.progress === null ? 0 : Math.min(100, goal.progress * 100)}
                aria-label={`${goal.name} progress`}
              />
              <dl className="grid grid-cols-2 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Saved</dt>
                <dd className="text-right">
                  <Money value={goal.current} /> of <Money value={goal.target} />
                </dd>
                <dt className="text-muted-foreground">Needed monthly</dt>
                <dd className="text-right">
                  <Money value={goal.required_monthly} />
                </dd>
                <dt className="text-muted-foreground">Short monthly</dt>
                <dd className="text-right">
                  <Money value={goal.behind_monthly} />
                </dd>
              </dl>
            </section>
          ))}
        </div>
      ) : (
        <Empty icon={GoalIcon} title="No goals yet">
          The onboard or plan skill records goals in profile/goals.json.
        </Empty>
      )}
    </div>
  )
}

export function Finances() {
  return (
    <Page>
      <PageTitle title="Finances" description="Read from the latest complete sync. Nothing here can trade or move money." />
      <Tabs defaultValue="overview">
        <TabsList className="mb-4 max-w-full overflow-x-auto [scrollbar-width:none]">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="accounts">Accounts</TabsTrigger>
          <TabsTrigger value="holdings">Holdings</TabsTrigger>
          <TabsTrigger value="cashflow">Cash flow</TabsTrigger>
          <TabsTrigger value="goals">Goals</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <Overview />
        </TabsContent>
        <TabsContent value="accounts">
          <Accounts />
        </TabsContent>
        <TabsContent value="holdings">
          <Holdings />
        </TabsContent>
        <TabsContent value="cashflow">
          <Cashflow />
        </TabsContent>
        <TabsContent value="goals">
          <Goals />
        </TabsContent>
      </Tabs>
    </Page>
  )
}
