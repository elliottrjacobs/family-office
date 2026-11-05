import { act, cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { Run, RunEvent } from "@/api/runs"
import { AdvisorAvatar, LiveAdvisorAvatar, publishRun } from "@/components/advisor-avatar"

const app = vi.hoisted(() => ({ connected: true }))
vi.mock("@/app-data", () => ({ useAppData: () => app }))

afterEach(() => {
  cleanup()
  publishRun("cio", null)
  app.connected = true
})

const run: Run = {
  id: "r1",
  skill: "cio",
  subject: "household",
  level: "household",
  deep: false,
  status: "running",
  session_id: "s1",
  report: "reports/cio/x.md",
  report_written: false,
  decisions: [],
  verify: null,
  error: null,
  cost_usd: 0,
  created: new Date().toISOString(),
}

describe("advisor avatars", () => {
  it("draws a robot for an advisor and keeps the icon for skills without one", () => {
    const { container } = render(
      <>
        <AdvisorAvatar name="plan" group="household" />
        <AdvisorAvatar name="journal" group="routine" />
      </>
    )
    expect(screen.getByRole("img", { name: "Planner idle" })).toBeDefined()
    expect(container.querySelectorAll("svg[data-advisor]")).toHaveLength(1)
  })

  it("follows the published conversation", () => {
    render(<LiveAdvisorAvatar advisor="cio" size={48} label />)
    expect(screen.getByRole("img", { name: "CIO idle" })).toBeDefined()
    const now = new Date().toISOString()
    const events: RunEvent[] = [
      { kind: "status", status: "running", seq: 1, at: now },
      { kind: "tool", id: "t1", name: "Bash", label: "Holdings", command: "fo holdings --json", seq: 2, at: now },
    ]
    act(() => publishRun("cio", { run, events }))
    expect(screen.getByRole("img", { name: "CIO reading" })).toBeDefined()
    expect(screen.getByText("Reading")).toBeDefined()
    act(() => publishRun("cio", null))
    expect(screen.getByRole("img", { name: "CIO idle" })).toBeDefined()
  })

  it("thinks for a queued run and sleeps when the server is unreachable", () => {
    const { rerender } = render(<LiveAdvisorAvatar advisor="cio" size={48} fallback={{ ...run, status: "queued" }} />)
    expect(screen.getByRole("img", { name: "CIO thinking" })).toBeDefined()
    app.connected = false
    rerender(<LiveAdvisorAvatar advisor="cio" size={64} fallback={{ ...run, status: "queued" }} />)
    expect(screen.getByRole("img", { name: "CIO sleeping" })).toBeDefined()
  })
})
