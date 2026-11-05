import { act, cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import {
  ADVISOR_IDS,
  ANTENNAS,
  defaultAppearance,
  EYE_KINDS,
  SHAPE_IDS,
  STATES,
} from "@/avatars/appearance"
import { Robot } from "@/avatars/Robot"
import { resetAppearance, saveAppearance } from "@/avatars/store"

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

function ids(container: Element) {
  return [...container.querySelectorAll("[id]")].map((node) => node.id)
}

describe("Robot", () => {
  it.each([24, 160])("renders an svg with the advisor's label at %i px", (size) => {
    render(<Robot advisor="cio" size={size} />)
    const svg = screen.getByRole("img", { name: "CIO idle" })
    expect(svg.tagName.toLowerCase()).toBe("svg")
    expect(svg.getAttribute("viewBox")).toBe("0 0 100 100")
    expect(svg.getAttribute("width")).toBe(String(size))
  })

  it("names the advisor and the state", () => {
    render(<Robot advisor="realestate" state="thinking" />)
    expect(screen.getByRole("img", { name: "Real estate thinking" })).toBeDefined()
  })

  it("scopes gradient ids per instance", () => {
    const { container } = render(
      <>
        <Robot advisor="cio" />
        <Robot advisor="cio" />
      </>,
    )
    const [first, second] = container.querySelectorAll("svg")
    const a = ids(first)
    const b = ids(second)
    expect(a.length).toBeGreaterThan(0)
    expect(new Set([...a, ...b]).size).toBe(a.length + b.length)
    // Every url(#…) reference points at a definition inside the same svg.
    for (const svg of [first, second]) {
      const own = new Set(ids(svg))
      for (const node of svg.querySelectorAll("[fill^='url('], [stroke^='url('], [filter^='url(']")) {
        for (const attr of ["fill", "stroke", "filter"]) {
          const match = /^url\(#(.+)\)$/.exec(node.getAttribute(attr) ?? "")
          if (match) expect(own.has(match[1])).toBe(true)
        }
      }
    }
  })

  it("omits the specular and rim layers for a matte finish", () => {
    const { container, rerender } = render(<Robot advisor="tax" size={160} />)
    expect(container.querySelector('[data-layer="specular"]')).not.toBeNull()
    expect(container.querySelector('[data-layer="rim"]')).not.toBeNull()
    rerender(<Robot advisor="tax" size={160} appearance={{ ...defaultAppearance("tax"), finish: "matte" }} />)
    expect(container.querySelector('[data-layer="specular"]')).toBeNull()
    expect(container.querySelector('[data-layer="rim"]')).toBeNull()
    expect(container.querySelector('[data-layer="shell"]')).not.toBeNull()
  })

  it("drops blur filters and the sheen at small sizes", () => {
    const { container, rerender } = render(<Robot advisor="macro" size={24} />)
    expect(container.querySelector("filter")).toBeNull()
    expect(container.querySelector('[data-layer="sheen"]')).toBeNull()
    expect(container.querySelector('[data-layer="glow"] circle')).not.toBeNull()
    rerender(<Robot advisor="macro" size={160} />)
    expect(container.querySelectorAll("filter")).toHaveLength(2)
    expect(container.querySelector('[data-layer="sheen"]')).not.toBeNull()
  })

  it("follows the stored look and re-renders after a save", () => {
    const { container } = render(<Robot advisor="cio" />)
    const shellStop = () => container.querySelector("linearGradient stop[offset='0.55']")?.getAttribute("stop-color")
    expect(shellStop()).toBe("#2F5BD3")
    act(() => {
      saveAppearance("cio", { ...defaultAppearance("cio"), shell: "#0EA5B7" })
    })
    expect(shellStop()).toBe("#0EA5B7")
    act(() => {
      resetAppearance("cio")
    })
    expect(shellStop()).toBe("#2F5BD3")
  })

  it("tilts the head in the error pose and adds z's when sleeping", () => {
    const { container, rerender } = render(<Robot advisor="risk" state="error" />)
    expect(container.querySelector('[data-part="head"]')?.getAttribute("transform")).toMatch(/^rotate/)
    rerender(<Robot advisor="risk" state="sleeping" />)
    expect(container.querySelector('[data-part="head"]')?.getAttribute("transform")).toBeNull()
    expect(container.querySelectorAll('[data-part="sleep"] text')).toHaveLength(2)
  })

  it("renders every advisor on every shape in every state", () => {
    for (const advisor of ADVISOR_IDS) {
      for (const [i, shape] of SHAPE_IDS.entries()) {
        const state = STATES[i % STATES.length]
        const look = {
          ...defaultAppearance(advisor),
          shape,
          eyes: EYE_KINDS[i % EYE_KINDS.length],
          antenna: ANTENNAS[i % ANTENNAS.length],
        }
        const { container, unmount } = render(<Robot advisor={advisor} appearance={look} state={state} />)
        expect(container.querySelector('[data-part="eyes"]')).not.toBeNull()
        unmount()
      }
    }
  })
})
