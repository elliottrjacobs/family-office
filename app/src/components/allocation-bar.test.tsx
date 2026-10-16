import { cleanup, render } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { AllocationBar, bandState } from "@/components/allocation-bar"

afterEach(cleanup)

describe("bandState", () => {
  it("places a weight inside, above, or below its band", () => {
    expect(bandState(0.55, 0.5, 0.7)).toBe("inside")
    expect(bandState(0.5, 0.5, 0.7)).toBe("inside")
    expect(bandState(0.7, 0.5, 0.7)).toBe("inside")
    expect(bandState(0.71, 0.5, 0.7)).toBe("above")
    expect(bandState(0.12, 0.2, 0.4)).toBe("below")
    expect(bandState(null, 0.2, 0.4)).toBe("unknown")
  })
})

describe("AllocationBar", () => {
  it.each([
    [0.6, "inside", null],
    [0.8, "above", "Over band"],
    [0.3, "below", "Under band"],
    [null, "unknown", null],
  ] as const)("renders weight %s as %s", (weight, state, label) => {
    const { container } = render(<AllocationBar name="Equity" weight={weight} min={0.5} max={0.7} />)
    const bar = container.querySelector("[data-state]")
    expect(bar?.getAttribute("data-state")).toBe(state)
    if (label) expect(container.textContent).toContain(label)
    else expect(container.textContent).not.toMatch(/Over band|Under band/)
    expect(container.textContent).toContain(weight === null ? "unknown" : `${(weight * 100).toFixed(1)}%`)
    expect(container.textContent).toContain("50%")
    expect(container.textContent).toContain("70%")
  })
})
