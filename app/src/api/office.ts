/** Typed office routes. Every decimal is parsed once here; views never see strings. */

import { get, num, nums, post } from "@/api/client"

type Decimal = number | null

interface Freshness {
  as_of: string | null
  stale_accounts: string[]
  stale_providers: string[]
}

// --- server and onboarding ---------------------------------------------------------

export interface SyncRow {
  run_id: string
  as_of: string
  provider: string
  status: "complete" | "failed" | string
  reason?: string
  account_ids?: string[]
}

export interface Status {
  version: string
  mode: "office" | "onboarding"
  read_only: boolean
  chat: boolean
  remote: boolean
  identity: { login: string; name: string | null } | null
  office: {
    office: string
    read_only: boolean
    writer_host: boolean
    last_sync: SyncRow | null
  } | null
}

export type OnboardingState =
  | "no_office"
  | "uninitialized_path"
  | "unconnected"
  | "offline"
  | "never_synced"
  | "stale"
  | "ready"

export interface DoctorCheck {
  name: string
  status: "pass" | "warn" | "fail"
  reason: string
}

export interface DoctorItem extends DoctorCheck {
  command: string | null
  hint: string | null
}

export interface Onboarding {
  state: OnboardingState
  reason: string
  office: string | null
  candidate: string | null
  steps: { command: string; purpose: string }[]
  note: string | null
  providers: { provider: string; connected: boolean; accounts: number }[]
  doctor: DoctorItem[]
  last_sync: string | null
}

export const status = () => get<Status>("/api/status")
export const onboarding = () => get<Onboarding>("/api/onboarding")
export const chooseOffice = (path: string) => post<Onboarding>("/api/onboarding/path", { path })
export const doctor = () => get<DoctorCheck[]>("/api/doctor")
export const syncLog = () => get<SyncRow[]>("/api/sync")

// --- finances ----------------------------------------------------------------------

export interface NetWorth extends Freshness {
  total: Decimal
  groups: { name: string; value: Decimal }[]
  missing_accounts: string[]
}

export interface Band {
  name: string
  weight: Decimal
  min: number
  max: number
  drift_points: Decimal
  outside_band: boolean | null
}

export interface Allocation extends Freshness {
  weights: Record<string, Decimal>
  bands: Band[]
  unclassified: string[]
  total: Decimal
  excluded_accounts: string[]
  unclassified_accounts: string[]
}

export interface Position {
  account_id: string
  symbol: string
  qty: Decimal
  price: Decimal
  value: Decimal
  cost_basis: Decimal
  acquired_at: string | null
  as_of: string
}

export interface Positions extends Freshness {
  positions: Position[]
}

export interface CashflowMonth {
  month: string
  income: Decimal
  spend: Decimal
  net: Decimal
}

export interface Cashflow extends Freshness {
  months: CashflowMonth[]
}

export interface Spend extends Freshness {
  month: string
  spend: Decimal
  income: Decimal
  categories: Record<string, Decimal>
  transaction_count: number
}

export interface Goal {
  name: string
  target: Decimal
  current: Decimal
  progress: Decimal
  required_monthly: Decimal
  behind_monthly: Decimal
  status: "on_track" | "behind" | "unknown"
}

export interface Goals extends Freshness {
  goals: Goal[]
}

type Raw<T> = { [K in keyof T]: unknown }

export async function netWorth(): Promise<NetWorth> {
  const raw = await get<Raw<NetWorth> & { groups: Raw<NetWorth["groups"][number]>[] }>(
    "/api/networth"
  )
  return {
    ...(raw as unknown as NetWorth),
    total: num(raw.total),
    groups: raw.groups.map((g) => ({ name: String(g.name), value: num(g.value) })),
  }
}

export async function allocation(): Promise<Allocation> {
  const raw = await get<Allocation & { bands: Raw<Band>[]; weights: Record<string, unknown> }>(
    "/api/allocation"
  )
  return {
    ...raw,
    total: num(raw.total),
    weights: nums(raw.weights),
    bands: raw.bands.map((b) => ({
      name: String(b.name),
      weight: num(b.weight),
      min: num(b.min) ?? 0,
      max: num(b.max) ?? 0,
      drift_points: num(b.drift_points),
      outside_band: b.outside_band as boolean | null,
    })),
  }
}

export async function positions(): Promise<Positions> {
  const raw = await get<Positions & { positions: Raw<Position>[] }>("/api/positions")
  return {
    ...raw,
    positions: raw.positions.map((p) => ({
      account_id: String(p.account_id),
      symbol: String(p.symbol),
      qty: num(p.qty),
      price: num(p.price),
      value: num(p.value),
      cost_basis: num(p.cost_basis),
      acquired_at: (p.acquired_at as string | null) ?? null,
      as_of: String(p.as_of),
    })),
  }
}

export async function cashflow(months = 6): Promise<Cashflow> {
  const raw = await get<Cashflow & { months: Raw<CashflowMonth>[] }>(
    `/api/cashflow?months=${months}`
  )
  return {
    ...raw,
    months: raw.months.map((m) => ({ month: String(m.month), ...nums({ income: m.income, spend: m.spend, net: m.net }) })),
  }
}

export async function spend(month: string): Promise<Spend> {
  const raw = await get<Spend & { categories: Record<string, unknown> }>(
    `/api/spend?month=${encodeURIComponent(month)}`
  )
  return {
    ...raw,
    spend: num(raw.spend),
    income: num(raw.income),
    categories: nums(raw.categories),
  }
}

export async function goals(): Promise<Goals> {
  const raw = await get<Goals & { goals: Raw<Goal>[] }>("/api/goals")
  return {
    ...raw,
    goals: raw.goals.map((g) => ({
      name: String(g.name),
      status: g.status as Goal["status"],
      ...nums({
        target: g.target,
        current: g.current,
        progress: g.progress,
        required_monthly: g.required_monthly,
        behind_monthly: g.behind_monthly,
      }),
    })),
  }
}

// --- notebook ----------------------------------------------------------------------

export interface Clause {
  metric: string
  op: string
  threshold: string
  quarters: number | null
}

export interface Decision {
  id: string
  date: string
  subject: string
  action: string
  thesis: string
  invalidate: string
  when: Clause[]
  conviction: "HIGH" | "MEDIUM" | "LOW"
  source: string
  report: string | null
  context_level: "none" | "household" | "full"
  status: "open" | "closed"
  outcome?: "hit" | "miss" | "neutral" | "unknown"
  note?: string
  judged_until?: string
}

export interface Correction {
  id: string
  date: string
  scope: string
  text: string
}

export interface ReviewItem {
  id: string
  subject: string
  breached: boolean
  needs_judgment: boolean
  due_for_verdict: boolean
}

export interface Review {
  date: string
  decisions: ReviewItem[]
  breaches: number
}

export const decisions = () => get<Decision[]>("/api/decisions")
export const corrections = () => get<Correction[]>("/api/corrections")
export const review = () => get<Review>("/api/review")

// --- reports and profile -----------------------------------------------------------

export interface ReportFrontmatter {
  kind: string
  subject: string
  date: string
  summary?: string
  model?: string
  context_level?: string
  prior?: string | null
  decision_ids?: string[]
  playbooks?: string[]
  legacy?: boolean
}

export interface ReportEntry {
  path: string
  frontmatter: ReportFrontmatter
  summary: string
}

export interface Report {
  path: string
  frontmatter: ReportFrontmatter
  body: string
}

export const reports = () => get<{ reports: ReportEntry[]; parse_errors: string[] }>("/api/reports")
export const report = (path: string) => get<Report>(`/api/report?path=${encodeURIComponent(path)}`)

export interface ProfileFile {
  name: string
  file: string
  text: string
  data: unknown
  error: string | null
}

export const profileFiles = () => get<{ name: string; file: string }[]>("/api/profile")
export const profile = (name: string) => get<ProfileFile>(`/api/profile/${encodeURIComponent(name)}`)

export interface PublicConfig {
  settings: Record<string, unknown>
  secrets: Record<string, unknown>
}

export const config = () => get<PublicConfig>("/api/config")

// --- advisors ----------------------------------------------------------------------

export type Level = "none" | "household" | "full"
export type Group = "household" | "research" | "specialists" | "routine" | "playbooks"

export interface Advisor {
  name: string
  description: string
  group: Group
  tier: "fast" | "balanced" | "strong"
  default_context: Level
  allowed_context: Level[]
  invocation: "implicit" | "explicit"
  args: string
  deep: boolean
  commands: string[]
  report_kind: string
}

export interface Registry {
  skills: Advisor[]
  agents: { name: string; description: string; tier: string }[]
}

export const skills = () => get<Registry>("/api/skills")

export interface LevelInfo {
  summary: string
  reads: string[]
  files: string[]
}

export const levels = () => get<Record<Level, LevelInfo>>("/api/levels")
