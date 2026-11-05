import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { App } from "@/App"
import { COMBINATIONS, SIZES } from "@/views/playground"

const fetch = vi.fn()

beforeEach(() => {
  fetch.mockReset()
  vi.stubGlobal("fetch", fetch)
  vi.stubGlobal(
    "EventSource",
    vi.fn(() => {
      throw new Error("The playground opened an event stream.")
    })
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.localStorage.clear()
  window.history.pushState(null, "", "/")
})

function open(url: string) {
  window.history.pushState(null, "", url)
  return render(<App />)
}

const robots = (root: ParentNode) => root.querySelectorAll("svg[data-advisor]")

describe("Playground", () => {
  it("renders every section without an office or a single API call", () => {
    open("/playground/robots")
    for (const title of ["Defaults", "States", "Combinations", "Editor", "Customize UIs"]) {
      expect(screen.getByRole("heading", { name: title })).toBeDefined()
    }
    expect(screen.getByRole("complementary", { name: "CIO inspector" })).toBeDefined()
    expect(screen.getByText("Household brief, about 2,400 tokens")).toBeDefined()
    expect(fetch).not.toHaveBeenCalled()
  })

  it("?shot=defaults renders only the defaults: 13 robots at 4 sizes on 2 panels", () => {
    const { container } = open("/playground/robots?shot=defaults&theme=dark")
    expect(container.querySelector("header")).toBeNull()
    expect(container.querySelectorAll("section")).toHaveLength(1)
    expect(SIZES).toHaveLength(4)
    expect(robots(container)).toHaveLength(13 * 4 * 2)
    expect(container.querySelectorAll("[data-panel=light] svg[data-advisor]")).toHaveLength(52)
    expect(container.querySelectorAll("[data-panel=dark] svg[data-advisor]")).toHaveLength(52)
    expect(container.querySelector("[data-shot=defaults]")?.closest(".dark")).not.toBeNull()
  })

  it("?shot=states renders the eight states for the CIO", () => {
    const { container } = open("/playground/robots?shot=states")
    const all = robots(container)
    expect(all).toHaveLength(8)
    expect([...all].every((svg) => svg.getAttribute("data-advisor") === "cio")).toBe(true)
    expect(screen.getByRole("img", { name: "CIO speaking" })).toBeDefined()
    expect(screen.getByRole("img", { name: "CIO sleeping" })).toBeDefined()
  })

  it("?shot=combinations renders the six named presets", () => {
    const { container } = open("/playground/robots?shot=combinations&theme=light")
    expect(robots(container)).toHaveLength(6)
    for (const { name } of COMBINATIONS) expect(screen.getByText(name)).toBeDefined()
  })

  it("marks a shot ready once it has rendered", async () => {
    const { container } = open("/playground/robots?shot=states")
    await vi.waitFor(() => expect(container.querySelector("[data-ready=true]")).not.toBeNull())
  })

  it("applies a pasted config through parseAppearance and saves it", () => {
    open("/playground/robots?shot=editor")
    const area = screen.getByLabelText("Appearance JSON")
    fireEvent.change(area, { target: { value: '{"version":1,"shape":"hexagon","trim":"brass","bogus":true}' } })
    fireEvent.click(screen.getByRole("button", { name: "Apply" }))
    const saved = JSON.parse(window.localStorage.getItem("fo.avatar.v1.cio") ?? "null")
    expect(saved).toMatchObject({ shape: "hexagon", trim: "brass", shell: "#2F5BD3", antenna: "compass" })
    expect(saved.bogus).toBeUndefined()
  })
})
