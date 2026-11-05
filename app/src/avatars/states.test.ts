import { act, renderHook } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { Run, RunEvent, RunStatus } from "@/api/runs"
import {
  decayLevel,
  raiseLevel,
  stateFromRun,
  TIMING,
  toolState,
  useAvatarState,
  useSpeakingLevel,
} from "@/avatars/states"

const T0 = Date.parse("2026-11-04T12:00:00Z")
const at = (ms: number) => new Date(T0 + ms).toISOString()

function makeRun(status: RunStatus): Run {
  return {
    id: "r1",
    skill: "cio",
    subject: "household",
    level: "household",
    deep: false,
    status,
    session_id: "s1",
    report: "reports/cio/2026-11-04-household.md",
    report_written: false,
    decisions: [],
    verify: null,
    error: null,
    cost_usd: 0,
    created: at(0),
  }
}

// A synthetic run, in order, each event a second after the last.
const RECORDED: RunEvent[] = [
  { kind: "status", status: "queued" },
  { kind: "user", text: "/cio household" },
  { kind: "status", status: "running" },
  { kind: "init", session_id: "s1", model: "m" },
  { kind: "tool", id: "t1", name: "Bash", label: "Holdings", command: "fo holdings --json" },
  { kind: "tool_result", id: "t1", ok: true, output: "{}" },
  { kind: "tool", id: "t2", name: "Read", label: "Read policy.md", path: "policy.md" },
  { kind: "tool", id: "t3", name: "Bash", label: "Write report", command: "fo report write --kind cio" },
  { kind: "tool_result", id: "t3", ok: true, output: "ok" },
  { kind: "tool", id: "t4", name: "Edit", label: "Edit report", path: "reports/cio/2026-11-04-household.md" },
  { kind: "delta", text: "The portfolio " },
  { kind: "delta", text: "is within policy." },
  { kind: "text", text: "The portfolio is within policy." },
  { kind: "status", status: "verifying" },
  {
    kind: "result",
    ok: true,
    subtype: "success",
    text: "The portfolio is within policy.",
    cost_usd: 0.1,
    denials: [],
  },
  { kind: "status", status: "completed" },
].map((event, i) => ({ ...event, seq: i + 1, at: at((i + 1) * 1000) }) as RunEvent)

/** The state right after event `index` arrives, 100 ms later. */
function stepState(index: number, status: RunStatus = "queued") {
  const events = RECORDED.slice(0, index + 1)
  return stateFromRun(makeRun(status), events, { serverReachable: true, now: T0 + (index + 1) * 1000 + 100 })
}

afterEach(() => {
  vi.useRealTimers()
})

describe("stateFromRun", () => {
  it("follows a recorded run through thinking, reading, writing, speaking and done", () => {
    const states = RECORDED.map((_, i) => stepState(i))
    expect(states).toEqual([
      "thinking", // queued
      "thinking", // the prompt
      "thinking", // running, no tool yet
      "thinking", // init
      "reading", // fo holdings
      "reading", // its result
      "reading", // Read policy.md
      "writing", // fo report write
      "writing", // its result
      "writing", // Edit under reports/
      "speaking", // first delta
      "speaking", // second delta
      "thinking", // the full text, no delta streaming now
      "thinking", // verifying
      "thinking", // the result while verifying
      "done", // completed
    ])
  })

  it("stops speaking 1.5 s after the last delta", () => {
    const events = RECORDED.slice(0, 11)
    const last = T0 + 11_000
    const run = makeRun("running")
    expect(stateFromRun(run, events, { serverReachable: true, now: last + TIMING.speaking })).toBe("speaking")
    expect(stateFromRun(run, events, { serverReachable: true, now: last + TIMING.speaking + 1 })).toBe("thinking")
  })

  it("goes idle a short while after the run finishes", () => {
    const end = T0 + RECORDED.length * 1000
    const run = makeRun("completed")
    expect(stateFromRun(run, RECORDED, { serverReachable: true, now: end + 1000 })).toBe("done")
    expect(stateFromRun(run, RECORDED, { serverReachable: true, now: end + TIMING.finished + 1 })).toBe("idle")
    // An old run with no stream at all is idle.
    expect(stateFromRun(run, [], { serverReachable: true, now: end + 60_000 })).toBe("idle")
  })

  it("maps failed to error, and cancelled and partial to idle", () => {
    const end = (status: RunStatus) => [
      ...RECORDED.slice(0, 5),
      { kind: "status", status, seq: 6, at: at(6000) } as RunEvent,
    ]
    const now = T0 + 6500
    expect(stateFromRun(makeRun("running"), end("failed"), { serverReachable: true, now })).toBe("error")
    expect(stateFromRun(makeRun("running"), end("cancelled"), { serverReachable: true, now })).toBe("idle")
    expect(stateFromRun(makeRun("running"), end("partial"), { serverReachable: true, now })).toBe("idle")
    expect(stateFromRun(makeRun("failed"), [], { serverReachable: true, now: T0 + 100 })).toBe("error")
  })

  it("sleeps when the server is unreachable and idles with no run", () => {
    expect(stateFromRun(makeRun("running"), RECORDED.slice(0, 6), { serverReachable: false })).toBe("sleeping")
    expect(stateFromRun(undefined, [], { serverReachable: true })).toBe("idle")
    expect(stateFromRun(null, [], { serverReachable: false })).toBe("sleeping")
  })

  it("counts only the current turn after a follow-up message", () => {
    const followUp: RunEvent[] = [
      ...RECORDED,
      { kind: "user", text: "And the tax side?", seq: 17, at: at(17_000) },
      { kind: "status", status: "queued", seq: 18, at: at(18_000) },
      { kind: "status", status: "running", seq: 19, at: at(19_000) },
    ]
    expect(stateFromRun(makeRun("completed"), followUp, { serverReachable: true, now: T0 + 19_100 })).toBe("thinking")
  })

  it("classifies tool calls", () => {
    expect(toolState({ name: "Bash", command: "fo report write --kind cio" })).toBe("writing")
    expect(toolState({ name: "Bash", command: "fo --json report write" })).toBe("writing")
    expect(toolState({ name: "Bash", command: "fo report show reports/x.md" })).toBe("reading")
    expect(toolState({ name: "Bash", command: "ls" })).toBe("thinking")
    expect(toolState({ name: "Read", path: "policy.md" })).toBe("reading")
    expect(toolState({ name: "Write", path: "reports/cio/a.md" })).toBe("writing")
    expect(toolState({ name: "Write", path: "notes.md" })).toBe("thinking")
    expect(toolState({ name: "Task" })).toBe("thinking")
  })

  it("re-evaluates when the speaking window closes", () => {
    vi.useFakeTimers({ now: T0 + 11_000 })
    const events = RECORDED.slice(0, 11)
    const { result } = renderHook(() => useAvatarState(makeRun("running"), events, true))
    expect(result.current).toBe("speaking")
    act(() => {
      vi.advanceTimersByTime(TIMING.speaking + 50)
    })
    expect(result.current).toBe("thinking")
  })
})

describe("speaking level", () => {
  it("rises with the delta length and decays to zero in about 300 ms", () => {
    expect(raiseLevel(0, 0)).toBe(0)
    expect(raiseLevel(0, 4)).toBeGreaterThan(0)
    expect(raiseLevel(0, 40)).toBeGreaterThan(raiseLevel(0, 4))
    expect(raiseLevel(0, 400)).toBe(1)
    expect(decayLevel(1, 150)).toBeCloseTo(0.5)
    expect(decayLevel(1, TIMING.decay)).toBe(0)
    expect(decayLevel(0.2, -10)).toBe(0.2)
  })

  it("rises on a new delta and decays to zero on animation frames", () => {
    vi.useFakeTimers()
    const first = RECORDED.slice(0, 10)
    const { result, rerender } = renderHook(({ events }) => useSpeakingLevel(events), {
      initialProps: { events: first },
    })
    expect(result.current).toBe(0)
    rerender({ events: RECORDED.slice(0, 11) })
    const peak = result.current
    expect(peak).toBeGreaterThan(0)
    act(() => {
      vi.advanceTimersByTime(100)
    })
    expect(result.current).toBeLessThan(peak)
    expect(result.current).toBeGreaterThan(0)
    act(() => {
      vi.advanceTimersByTime(400)
    })
    expect(result.current).toBe(0)
  })

  it("ignores deltas already present when it mounts", () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useSpeakingLevel(RECORDED.slice(0, 12)))
    expect(result.current).toBe(0)
  })

  it("stays at zero under reduced motion", () => {
    vi.useFakeTimers()
    const original = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: query.includes("reduce"),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia
    try {
      const { result, rerender } = renderHook(({ events }) => useSpeakingLevel(events), {
        initialProps: { events: RECORDED.slice(0, 10) },
      })
      rerender({ events: RECORDED.slice(0, 11) })
      expect(result.current).toBe(0)
    } finally {
      window.matchMedia = original
    }
  })
})
