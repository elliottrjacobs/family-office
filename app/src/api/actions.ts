/** Journal and correction actions; each is a thin call to the matching fo command. */

import { post } from "@/api/client"
import type { Correction, Level } from "@/api/office"

export type Outcome = "hit" | "miss" | "neutral" | "unknown"
export type Conviction = "HIGH" | "MEDIUM" | "LOW"

export interface DecisionForm {
  subject: string
  action: string
  thesis: string
  invalidate: string
  conviction: Conviction
  context_level: Level
  when: string[]
  report?: string
}

export const close = (id: string, outcome: Outcome, note: string) =>
  post<Record<string, unknown>>(`/api/decisions/${id}/close`, { outcome, note })

export const reopen = (id: string, reason: string) =>
  post<Record<string, unknown>>(`/api/decisions/${id}/reopen`, { reason })

export const judge = (id: string, until: string, note: string) =>
  post<Record<string, unknown>>(`/api/decisions/${id}/judge`, { until, note })

export const record = (form: DecisionForm) => post<{ id: string }>("/api/decisions", form)

export const correct = (text: string, scope: string) =>
  post<Correction>("/api/corrections", { text, scope })

export const retire = (id: string) => post<Correction>(`/api/corrections/${id}/retire`, {})
