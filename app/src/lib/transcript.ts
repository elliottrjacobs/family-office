/** A run's events folded into the conversation the advisor page shows. */

import type { RunEvent, RunStatus } from "@/api/runs"

export interface Step {
  id: string
  name: string
  label: string
  nested: boolean
  ok?: boolean
  output?: string
}

export type Item =
  | { type: "user"; seq: number; text: string }
  | { type: "assistant"; seq: number; text: string; streaming: boolean }
  | { type: "steps"; seq: number; steps: Step[] }
  | { type: "decision"; seq: number; id: string }

export interface Transcript {
  items: Item[]
  status: RunStatus | null
  last: number
  denied: number
}

export const empty: Transcript = { items: [], status: null, last: 0, denied: 0 }

/**
 * Pure and idempotent: an event at or below the last seen sequence number is ignored, so
 * a stored replay followed by the live stream never doubles an item.
 */
export function apply(state: Transcript, event: RunEvent): Transcript {
  if (event.seq <= state.last) return state
  const items = [...state.items]
  const next: Transcript = { ...state, items, last: event.seq }
  const tail = items[items.length - 1]
  switch (event.kind) {
    case "user":
      items.push({ type: "user", seq: event.seq, text: event.text })
      break
    case "delta":
      if (event.nested) break
      if (tail?.type === "assistant" && tail.streaming) {
        items[items.length - 1] = { ...tail, text: tail.text + event.text }
      } else {
        items.push({ type: "assistant", seq: event.seq, text: event.text, streaming: true })
      }
      break
    case "text":
      if (event.nested) break
      if (tail?.type === "assistant" && tail.streaming) {
        items[items.length - 1] = { type: "assistant", seq: event.seq, text: event.text, streaming: false }
      } else {
        items.push({ type: "assistant", seq: event.seq, text: event.text, streaming: false })
      }
      break
    case "tool": {
      const step: Step = { id: event.id, name: event.name, label: event.label, nested: Boolean(event.nested) }
      if (tail?.type === "steps") items[items.length - 1] = { ...tail, steps: [...tail.steps, step] }
      else items.push({ type: "steps", seq: event.seq, steps: [step] })
      break
    }
    case "tool_result":
      for (let i = items.length - 1; i >= 0; i--) {
        const item = items[i]
        if (item.type === "steps" && item.steps.some((s) => s.id === event.id)) {
          items[i] = {
            ...item,
            steps: item.steps.map((s) => (s.id === event.id ? { ...s, ok: event.ok, output: event.output } : s)),
          }
          break
        }
      }
      break
    case "decision":
      if (!items.some((i) => i.type === "decision" && i.id === event.id)) {
        items.push({ type: "decision", seq: event.seq, id: event.id })
      }
      break
    case "status":
      next.status = event.status
      break
    case "result":
      next.denied = state.denied + event.denials.length
      break
  }
  return next
}
