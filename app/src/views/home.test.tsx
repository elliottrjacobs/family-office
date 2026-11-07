import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import type { ChecklistItem } from "@/api/office"
import { ChecklistCard } from "@/views/home"

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

const items = (done: Partial<Record<string, boolean>> = {}): ChecklistItem[] =>
  [
    ["account_connected", "Connect an account"],
    ["first_sync", "Run the first sync"],
    ["first_run", "Talk to an advisor"],
    ["device_paired", "Pair a phone"],
  ].map(([id, label]) => ({ id, label, done: done[id] ?? false }))

describe("ChecklistCard", () => {
  it("lists only the open items with a count", () => {
    render(<ChecklistCard items={items({ account_connected: true, first_sync: true })} />)
    expect(screen.getByRole("heading", { name: "Getting started" })).toBeDefined()
    expect(screen.getByText("2 of 4 done")).toBeDefined()
    expect(screen.getByText("Talk to an advisor")).toBeDefined()
    expect(screen.getByText("Pair a phone")).toBeDefined()
    expect(screen.queryByText("Connect an account")).toBeNull()
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
  })

  it("is hidden when every item is done", () => {
    const { container } = render(
      <ChecklistCard
        items={items({ account_connected: true, first_sync: true, first_run: true, device_paired: true })}
      />
    )
    expect(container.innerHTML).toBe("")
  })

  it("Dismiss hides it and remembers the choice", () => {
    const first = render(<ChecklistCard items={items()} />)
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
    expect(first.container.innerHTML).toBe("")
    expect(window.localStorage.getItem("fo.checklist.dismissed.v1")).toBe("1")
    first.unmount()
    const again = render(<ChecklistCard items={items()} />)
    expect(again.container.innerHTML).toBe("")
  })
})
