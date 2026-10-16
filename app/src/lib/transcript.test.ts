import { describe, expect, it } from "vitest"

import type { RunEvent } from "@/api/runs"
import { apply, empty, type Transcript } from "@/lib/transcript"

const events: RunEvent[] = [
  { seq: 1, kind: "user", text: "/research ACME --level household" },
  { seq: 2, kind: "status", status: "running" },
  { seq: 3, kind: "init", session_id: "s", model: "m" },
  { seq: 4, kind: "tool", id: "t1", name: "Bash", label: "Start research", command: "fo start research ACME" },
  { seq: 5, kind: "tool_result", id: "t1", ok: true, output: "{}" },
  { seq: 6, kind: "tool", id: "t2", name: "Bash", label: "ls", command: "ls" },
  { seq: 7, kind: "tool_result", id: "t2", ok: false, output: "PreToolUse:Bash hook error: denied" },
  { seq: 8, kind: "delta", text: "Here is " },
  { seq: 9, kind: "delta", text: "the answer." },
  { seq: 10, kind: "text", text: "Here is the answer." },
  { seq: 11, kind: "decision", id: "01M50V918GZEEPD9WHWV3M7CH6" },
  { seq: 12, kind: "tool", id: "t3", name: "Write", label: "Write reports/x.md", path: "reports/x.md" },
  { seq: 13, kind: "tool_result", id: "t3", ok: true, output: "ok" },
  {
    seq: 14,
    kind: "result",
    ok: true,
    subtype: "success",
    text: "Here is the answer.",
    cost_usd: 0.2,
    denials: [{ id: "t2", name: "Bash", label: "ls" }],
  },
  { seq: 15, kind: "status", status: "verifying" },
  { seq: 16, kind: "status", status: "completed" },
]

const run = (list: RunEvent[], start: Transcript = empty) => list.reduce(apply, start)

describe("transcript", () => {
  it("groups tool steps, folds streamed text, and keeps decisions and status", () => {
    const state = run(events)
    expect(state.items.map((i) => i.type)).toEqual(["user", "steps", "assistant", "decision", "steps"])
    const [user, steps, assistant] = state.items
    expect(user).toMatchObject({ text: "/research ACME --level household" })
    expect(steps).toMatchObject({ type: "steps" })
    if (steps.type !== "steps") throw new Error("steps")
    expect(steps.steps.map((s) => [s.label, s.ok])).toEqual([
      ["Start research", true],
      ["ls", false],
    ])
    expect(assistant).toMatchObject({ text: "Here is the answer.", streaming: false })
    expect(state.status).toBe("completed")
    expect(state.denied).toBe(1)
    expect(state.last).toBe(16)
  })

  it("shows streamed text before the final block arrives", () => {
    const state = run(events.slice(0, 9))
    const last = state.items[state.items.length - 1]
    expect(last).toMatchObject({ type: "assistant", text: "Here is the answer.", streaming: true })
  })

  it("gives the same transcript for a replay followed by live events", () => {
    const stored = events.filter((e) => e.kind !== "delta")
    const reattached = run(events.slice(9), run(stored.slice(0, 7)))
    expect(reattached.items).toEqual(run(stored).items)
    expect(run([...stored, ...stored]).items).toEqual(run(stored).items)
  })

  it("starts a new turn for each user message", () => {
    const followUp: RunEvent[] = [
      { seq: 17, kind: "user", text: "And BETA?" },
      { seq: 18, kind: "text", text: "BETA too." },
      { seq: 19, kind: "status", status: "awaiting_input" },
    ]
    const state = run([...events, ...followUp])
    expect(state.items.slice(-2).map((i) => i.type)).toEqual(["user", "assistant"])
    expect(state.status).toBe("awaiting_input")
  })
})
