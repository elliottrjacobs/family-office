import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
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
  window.localStorage.clear()
})

const stored = () => JSON.parse(window.localStorage.getItem("fo.avatar.v1.cio") ?? "null")
const shellStop = (container: HTMLElement) =>
  container.querySelector("[data-preview] linearGradient stop[offset='0.55']")?.getAttribute("stop-color")

describe("AdvisorInspector", () => {
  it("shows the advisor, what it reads, where it writes and the footer note", () => {
    render(<AdvisorInspector advisor={cio} />)
    expect(screen.getByRole("img", { name: "CIO idle" })).toBeDefined()
    expect(screen.getByText("What CIO reads")).toBeDefined()
    expect(screen.getByText("reports/cio/")).toBeDefined()
    expect(screen.getByText(/Nothing here can trade or move money/)).toBeDefined()
    expect(screen.queryByRole("button", { name: /Reset to/ })).toBeNull()
  })

  it("picking a swatch updates the preview's shell and persists through the store", () => {
    const { container } = render(<AdvisorInspector advisor={cio} />)
    expect(shellStop(container)).toBe("#2F5BD3")
    const colors = screen.getByRole("radiogroup", { name: "Color" })
    expect(within(colors).getByRole("radio", { name: "Cobalt" }).getAttribute("aria-checked")).toBe("true")
    fireEvent.click(within(colors).getByRole("radio", { name: "Teal" }))
    expect(shellStop(container)).toBe("#0EA5B7")
    expect(stored().shell).toBe("#0EA5B7")
    expect(within(colors).getByRole("radio", { name: "Teal" }).getAttribute("aria-checked")).toBe("true")
  })

  it("moves through the swatches with the arrow keys", () => {
    render(<AdvisorInspector advisor={cio} />)
    const colors = screen.getByRole("radiogroup", { name: "Color" })
    fireEvent.keyDown(within(colors).getByRole("radio", { name: "Cobalt" }), { key: "ArrowRight" })
    expect(stored().shell).toBe("#2E9CEB")
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Sky")
  })

  it("reveals a colour input for a custom shell", () => {
    render(<AdvisorInspector advisor={cio} />)
    expect(screen.queryByLabelText(/Custom color #/)).toBeNull()
    fireEvent.click(screen.getByRole("radio", { name: "Custom color" }))
    const input = screen.getByLabelText(/Custom color #/)
    fireEvent.change(input, { target: { value: "#123456" } })
    expect(stored().shell).toBe("#123456")
  })

  it("Reset to Cobalt restores the default", () => {
    const { container } = render(<AdvisorInspector advisor={cio} />)
    fireEvent.click(screen.getByRole("radio", { name: "Pink" }))
    fireEvent.click(screen.getByRole("button", { name: "Reset to Cobalt" }))
    expect(shellStop(container)).toBe("#2F5BD3")
    expect(window.localStorage.getItem("fo.avatar.v1.cio")).toBeNull()
    expect(screen.queryByRole("button", { name: /Reset to/ })).toBeNull()
  })

  it("keeps More closed by default and composes its options into the saved config", async () => {
    render(<AdvisorInspector advisor={cio} />)
    expect(screen.queryByText("Shape")).toBeNull()
    expect(screen.queryByRole("radiogroup", { name: "Antenna" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "More" }))

    fireEvent.click(screen.getByRole("combobox", { name: "Shape" }))
    const hexagon = await screen.findByRole("option", { name: "Hexagon" })
    // A real press starts on the item; Base UI ignores a click that did not.
    fireEvent.pointerDown(hexagon, { pointerType: "mouse" })
    fireEvent.click(hexagon)
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Antenna" })).getByRole("radio", { name: "None" }))
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Trim" })).getByRole("radio", { name: "Brass" }))
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Screen glow" })).getByRole("radio", { name: "Amber" }))

    expect(stored()).toMatchObject({ shape: "hexagon", antenna: "none", trim: "brass", screen: "amber", shell: "#2F5BD3" })
    expect(screen.getByRole("button", { name: "Reset to Cobalt" })).toBeDefined()
  })
})
