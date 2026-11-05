/** Advisor chat: runner status, preview, runs, and their event streams. */

import { get, post } from "@/api/client"
import type { Decision, Level, ReportFrontmatter } from "@/api/office"

export type RunStatus =
  | "queued"
  | "running"
  | "verifying"
  | "completed"
  | "partial"
  | "failed"
  | "awaiting_input"
  | "cancelled"

export const ACTIVE: RunStatus[] = ["queued", "running", "verifying"]

export type Effort = "low" | "medium" | "high"

export const ENGINE_LABELS: Record<string, string> = { claude: "Claude Code", codex: "Codex" }

export const engineLabel = (name: string) => ENGINE_LABELS[name] ?? name

export interface Run {
  id: string
  skill: string
  subject: string
  level: Level
  deep: boolean
  status: RunStatus
  session_id: string | null
  report: string
  report_written: boolean
  decisions: string[]
  verify: { valid: boolean; reason: string | null } | null
  error: { reason: string; message: string } | null
  cost_usd: number
  created: string
  // Absent on runs recorded before engines were selectable.
  engine?: string
  model?: string | null
  effort?: Effort | null
  reported_model?: string | null
  // Web search and fetch, on only at level none; absent on runs recorded before.
  web?: boolean
  web_count?: number
}

interface Base {
  seq: number
  at?: string
  nested?: boolean
}

export type RunEvent = Base &
  (
    | { kind: "user"; text: string }
    | { kind: "init"; session_id: string | null; model: string | null; tools?: string[] }
    | { kind: "text"; text: string }
    | { kind: "delta"; text: string }
    | { kind: "tool"; id: string; name: string; label: string; command?: string; path?: string }
    | { kind: "tool_result"; id: string; ok: boolean; output: string }
    | { kind: "decision"; id: string }
    | { kind: "web"; action: "fetch" | "search"; value: string }
    | { kind: "status"; status: RunStatus }
    | {
        kind: "result"
        ok: boolean
        subtype: string
        text: string
        cost_usd: number | null
        denials: { id: string; name: string; label: string }[]
      }
  )

/** An engine's defaults from [serve.engines.<name>] in office.toml. */
export interface EngineDefaults {
  model: string
  effort: Effort
  max_budget_usd: number
  enabled: boolean
}

export interface EngineStatus {
  name: string
  usable: boolean
  version: string | null
  reason: string | null
  message: string | null
  defaults: EngineDefaults | null
}

export interface RunnerStatus {
  ready: boolean
  default?: string
  deep?: boolean
  engines?: EngineStatus[]
  reason?: string
  message?: string
}

/** The curated models per engine (package data) with the office's current defaults. */
export interface ModelCatalog {
  engines: Record<
    string,
    { label: string; efforts: Effort[]; models: { id: string; label: string; recommended?: boolean }[] }
  >
  default: string
  defaults: Record<string, EngineDefaults>
}

export interface EngineChoice {
  engine: string
  model: string
  effort: Effort
}

export interface Preview {
  skill: string
  subject: string
  level: Level
  web?: boolean
  deep_available: boolean
  chat: boolean
  brief: {
    status: "ok" | "failed"
    reason?: string
    data?: {
      level: Level
      corrections: { id: string; scope: string; text: string }[]
      decisions: Pick<Decision, "id" | "subject" | "action" | "thesis" | "invalidate">[]
      estimated_tokens: number
      warnings: string[]
    }
  }
  prior: { status: "ok" | "failed"; data?: { path: string; frontmatter: ReportFrontmatter } | null }
  report: { status: "ok" | "failed"; data?: { path: string } }
}

export const runnerStatus = () => get<RunnerStatus>("/api/runner")

export const models = () => get<ModelCatalog>("/api/models")

export const preview = (skill: string, subject: string, level: Level) =>
  get<Preview>(
    `/api/advisors/${encodeURIComponent(skill)}/preview?subject=${encodeURIComponent(subject)}&level=${level}`
  )

export const runs = () => get<Run[]>("/api/runs")

export const run = (id: string) => get<Run>(`/api/runs/${encodeURIComponent(id)}`)

export const launch = (skill: string, subject: string, level: Level, deep: boolean, choice?: EngineChoice) =>
  post<Run>("/api/runs", { skill, subject, level, deep, ...choice })

export const reply = (id: string, text: string) => post<Run>(`/api/runs/${encodeURIComponent(id)}/message`, { text })

export const cancel = (id: string) => post<Run>(`/api/runs/${encodeURIComponent(id)}/cancel`, {})

/** Replay events after `after`, then follow the run; `onEnd` fires when it is finished. */
export function follow(id: string, after: number, onEvent: (event: RunEvent) => void, onEnd: () => void) {
  const source = new EventSource(`/api/runs/${encodeURIComponent(id)}/events?after=${after}`, { withCredentials: true })
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as RunEvent)
    } catch {
      // A malformed event is skipped.
    }
  }
  source.addEventListener("end", () => {
    source.close()
    onEnd()
  })
  return () => source.close()
}
