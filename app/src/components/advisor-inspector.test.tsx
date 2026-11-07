import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { Advisor } from "@/api/office"
import { AdvisorInspector } from "@/components/advisor-inspector"

const app = vi.hoisted(() => ({ connected: true }))
vi.mock("@/app-data", () => ({ useAppData: () => app }))

const cio: Advisor = {
  name: "cio",
  description: "Whole-portfolio decisions against your policy statement.",
  group: "household",
  tier: "strong",
  default_context: "household",
  allowed_context: ["none", "household", "full"],
  invocation: "implicit",
  args: "",
  deep: false,
  commands: ["allocation"],
  report_kind: "cio",
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("AdvisorInspector", () => {
  it("shows the advisor, what it reads, where it writes and the footer note", () => {
    render(<AdvisorInspector advisor={cio} />)
    expect(screen.getByRole("heading", { name: "CIO" })).toBeDefined()
    expect(screen.getByText("What CIO reads")).toBeDefined()
    expect(screen.getByText("reports/cio/")).toBeDefined()
    expect(screen.getByText(/Nothing here can trade or move money/)).toBeDefined()
  })

  it("shows no robot or appearance controls", () => {
    const { container } = render(<AdvisorInspector advisor={cio} />)
    expect(container.querySelector("svg[role='img']")).toBeNull()
    expect(screen.queryByRole("radiogroup", { name: "Color" })).toBeNull()
  })

  it("lists fixed reads without calling the API", () => {
    render(<AdvisorInspector advisor={cio} reads={["Household brief"]} />)
    expect(screen.getByText("Household brief")).toBeDefined()
  })
})
