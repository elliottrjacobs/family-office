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
}

interface Base {
  seq: number
  at?: string
  nested?: boolean
}

export type RunEvent = Base &
  (
    | { kind: "user"; text: string }
    | { kind: "init"; session_id: string | null; model: string | null }
    | { kind: "text"; text: string }
    | { kind: "delta"; text: string }
    | { kind: "tool"; id: string; name: string; label: string; command?: string; path?: string }
    | { kind: "tool_result"; id: string; ok: boolean; output: string }
    | { kind: "decision"; id: string }
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

export interface RunnerStatus {
  ready: boolean
  runner?: string
  version?: string
  deep?: boolean
  reason?: string
  message?: string
}

export interface Preview {
  skill: string
  subject: string
  level: Level
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

export const preview = (skill: string, subject: string, level: Level) =>
  get<Preview>(
    `/api/advisors/${encodeURIComponent(skill)}/preview?subject=${encodeURIComponent(subject)}&level=${level}`
  )

export const runs = () => get<Run[]>("/api/runs")

export const run = (id: string) => get<Run>(`/api/runs/${id}`)

export const launch = (skill: string, subject: string, level: Level, deep: boolean) =>
  post<Run>("/api/runs", { skill, subject, level, deep })

export const reply = (id: string, text: string) => post<Run>(`/api/runs/${id}/message`, { text })

export const cancel = (id: string) => post<Run>(`/api/runs/${id}/cancel`, {})

/** Replay events after `after`, then follow the run; `onEnd` fires when it is finished. */
export function follow(id: string, after: number, onEvent: (event: RunEvent) => void, onEnd: () => void) {
  const source = new EventSource(`/api/runs/${id}/events?after=${after}`, { withCredentials: true })
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
