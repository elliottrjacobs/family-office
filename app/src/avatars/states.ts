// What an advisor robot is doing, read from the run and its event stream (U19), and the
// speaking amplitude that drives its mouth while text streams in.

import * as React from "react"

import type { RobotState } from "@/avatars/appearance"
import type { Run, RunEvent, RunStatus } from "@/api/runs"

export type AvatarState = RobotState

/** Timing for the mapping, in milliseconds. */
export const TIMING = {
  /** A streamed delta this recent makes the robot speak. */
  speaking: 1500,
  /** A finished run shows done or error this long, then the robot goes idle. */
  finished: 8000,
  /** The speaking amplitude falls from 1 to 0 in this long. */
  decay: 300,
} as const

const ACTIVE: readonly RunStatus[] = ["queued", "running", "verifying"]
const READERS = new Set(["Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"])
const WRITERS = new Set(["Write", "Edit", "MultiEdit", "NotebookEdit"])
// `fo` with any global options, then a subcommand; `fo report write` is the writing one.
const FO = /^\s*fo(\s|$)/
const REPORT_WRITE = /^\s*fo(\s+-{1,2}\S+)*\s+report\s+write(\s|$)/

type Tool = Extract<RunEvent, { kind: "tool" }>

function time(event: { at?: string } | undefined): number | null {
  if (!event?.at) return null
  const value = Date.parse(event.at)
  return Number.isNaN(value) ? null : value
}

/** The state one tool call shows: reading for fo commands and reads, writing for reports. */
export function toolState(tool: Pick<Tool, "name" | "command" | "path">): AvatarState {
  const command = tool.command ?? ""
  if (tool.name === "Bash") {
    if (REPORT_WRITE.test(command)) return "writing"
    return FO.test(command) ? "reading" : "thinking"
  }
  if (WRITERS.has(tool.name)) {
    const path = (tool.path ?? "").replace(/^\.\//, "")
    return path.startsWith("reports/") ? "writing" : "thinking"
  }
  return READERS.has(tool.name) ? "reading" : "thinking"
}

export interface Options {
  serverReachable: boolean
  /** The current time; tests pass a fixed clock. */
  now?: number
}

/**
 * Pure: the robot's state for `run` given the events seen so far. A status event in the
 * stream wins over the run record, which may be older. Only the current turn counts: events
 * before the latest user message belong to an earlier exchange.
 */
export function stateFromRun(
  run: Run | null | undefined,
  events: readonly RunEvent[],
  { serverReachable, now = Date.now() }: Options
): AvatarState {
  if (!serverReachable) return "sleeping"
  if (!run) return "idle"
  let start = 0
  let status: RunStatus = run.status
  let statusEvent: RunEvent | undefined
  for (let i = 0; i < events.length; i++) {
    const event = events[i]
    if (event.kind === "user") start = i
    if (event.kind === "status") {
      status = event.status
      statusEvent = event
    }
  }
  const turn = events.slice(start)
  let lastWork: RunEvent | undefined
  for (let i = turn.length - 1; i >= 0; i--) {
    const event = turn[i]
    if (event.nested && event.kind !== "tool") continue
    if (event.kind === "tool" || event.kind === "delta" || event.kind === "text") {
      lastWork = event
      break
    }
  }
  const at = time(lastWork)
  const speaking = lastWork?.kind === "delta" && at !== null && now - at <= TIMING.speaking

  if (ACTIVE.includes(status)) {
    if (status !== "running") return "thinking"
    if (speaking) return "speaking"
    if (lastWork?.kind === "tool") return toolState(lastWork)
    return "thinking"
  }
  if (status === "awaiting_input" && speaking) return "speaking"
  const finished = time(statusEvent) ?? time(events[events.length - 1]) ?? time({ at: run.created })
  if (finished === null || now - finished > TIMING.finished) return "idle"
  if (status === "completed") return "done"
  if (status === "failed") return "error"
  return "idle"
}

/** The next time `stateFromRun` may give a different answer without a new event, or null. */
export function nextChange(state: AvatarState, events: readonly RunEvent[], now: number): number | null {
  if (state !== "speaking" && state !== "done" && state !== "error") return null
  const last = time(events[events.length - 1])
  if (last === null) return null
  const window = state === "speaking" ? TIMING.speaking : TIMING.finished
  return Math.max(now, last + window + 1)
}

/** `stateFromRun` that re-evaluates when a time window runs out. */
export function useAvatarState(
  run: Run | null | undefined,
  events: readonly RunEvent[],
  serverReachable: boolean
): AvatarState {
  const [now, setNow] = React.useState(() => Date.now())
  const state = stateFromRun(run, events, { serverReachable, now })
  const next = nextChange(state, events, now)
  // A clock older than the newest event reads that event as just now, which it is; the
  // timer below advances the clock when a window closes.
  React.useEffect(() => {
    if (next === null) return
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(0, next - Date.now()))
    return () => window.clearTimeout(timer)
  }, [next])
  return state
}

// Speaking amplitude.

/** Pure: the amplitude after a delta of `length` characters arrives. */
export function raiseLevel(level: number, length: number): number {
  if (length <= 0) return level
  const target = Math.min(1, 0.25 + length / 32)
  return Math.min(1, Math.max(level, target))
}

/** Pure: the amplitude `elapsed` milliseconds later; it reaches zero within `TIMING.decay`. */
export function decayLevel(level: number, elapsed: number): number {
  return Math.max(0, level - Math.max(0, elapsed) / TIMING.decay)
}

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)"

function reducedQuery(): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(REDUCED_MOTION)
    : null
}

function subscribeMotion(onChange: () => void) {
  const query = reducedQuery()
  query?.addEventListener?.("change", onChange)
  return () => query?.removeEventListener?.("change", onChange)
}

/** Whether the viewer asked for reduced motion; false where the query is unavailable. */
export function useReducedMotion(): boolean {
  return React.useSyncExternalStore(
    subscribeMotion,
    () => reducedQuery()?.matches ?? false,
    () => false
  )
}

/**
 * The speaking amplitude, 0 to 1: each new top-level delta raises it by its length and it
 * decays to zero over about 300 ms on animation frames. Under reduced motion it stays 0.
 */
export function useSpeakingLevel(events: readonly RunEvent[]): number {
  const reduced = useReducedMotion()
  const [level, setLevel] = React.useState(0)
  const seen = React.useRef<number | null>(null)
  const frame = React.useRef<number | null>(null)

  React.useEffect(() => {
    const before = seen.current
    if (!events.length) {
      seen.current = 0
      return
    }
    const last = events[events.length - 1].seq
    seen.current = last
    // Events already there on mount are history, not speech.
    if (before === null || reduced) return
    // A different run numbers its events from the start again.
    const from = last < before ? 0 : before
    let raised: number | null = null
    for (const event of events) {
      if (event.seq <= from || event.kind !== "delta" || event.nested) continue
      raised = raiseLevel(raised ?? 0, event.text.length)
    }
    if (raised === null) return
    const peak = raised
    setLevel((current) => Math.max(current, peak))
  }, [events, reduced])

  React.useEffect(() => {
    if (reduced || level <= 0) return
    let previous: number | null = null
    const tick = (stamp: number) => {
      const elapsed = previous === null ? 0 : stamp - previous
      previous = stamp
      setLevel((current) => decayLevel(current, elapsed))
      frame.current = window.requestAnimationFrame(tick)
    }
    frame.current = window.requestAnimationFrame(tick)
    return () => {
      if (frame.current !== null) window.cancelAnimationFrame(frame.current)
      frame.current = null
    }
    // Restart the loop only when it starts from rest, not on every decayed frame.
  }, [reduced, level > 0]) // eslint-disable-line react-hooks/exhaustive-deps

  return reduced ? 0 : level
}
