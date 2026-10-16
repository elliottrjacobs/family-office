import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { Advisor } from "@/api/office"
import { LaunchPanel } from "@/components/launch-panel"

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const base: Advisor = {
  name: "lynch",
  description: "Score a stock.",
  group: "playbooks",
  tier: "balanced",
  default_context: "none",
  allowed_context: ["none", "household"],
  invocation: "implicit",
  args: "<subject>",
  deep: false,
  commands: ["score"],
  report_kind: "score",
}

describe("LaunchPanel", () => {
  it("offers only the advisor's allowed levels and hides deep when undeclared", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))
    render(<LaunchPanel advisor={base} deepAvailable={true} onLaunched={vi.fn()} />)
    const levels = screen.getAllByRole("radio").map((r) => r.textContent)
    expect(levels).toEqual(["None", "Household"])
    expect(screen.queryByRole("switch")).toBeNull()
  })

  it("shows deep only when the advisor declares it and the runner allows it", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))
    const research = { ...base, name: "research", deep: true, allowed_context: ["none", "household", "full"] as Advisor["allowed_context"] }
    const { rerender } = render(<LaunchPanel advisor={research} deepAvailable={true} onLaunched={vi.fn()} />)
    expect(screen.getAllByRole("radio")).toHaveLength(3)
    expect(screen.getByRole("switch")).toBeTruthy()
    rerender(<LaunchPanel advisor={research} deepAvailable={false} onLaunched={vi.fn()} />)
    expect(screen.queryByRole("switch")).toBeNull()
  })
})
