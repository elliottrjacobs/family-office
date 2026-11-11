import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"

import { Finances } from "@/views/finances"

vi.mock("@/api/use-api", () => ({
  useApi: (key: string) => ({
    loading: false,
    reload: vi.fn(),
    data: key === "cashflow" ? {
      months: [
        { month: "2026-07", income: 100, spend: 50, net: 50, partial: false, uncategorized_count: 0 },
        { month: "2026-08", income: 0, spend: 20, net: -20, partial: true, uncategorized_count: 2 },
      ],
    } : undefined,
  }),
}))

afterEach(cleanup)

it("marks partial months and explains uncategorized spending and transfer rules", () => {
  render(<Finances />)
  fireEvent.click(screen.getByRole("tab", { name: "Cash flow" }))
  expect(screen.getByText(/Aug.*2026.*\(so far\)/)).toBeDefined()
  expect(screen.getByText(/2 transactions are uncategorized; add category rules/)).toBeDefined()
  expect(screen.getByText(/Transfers and card payments are left out once a category rule/)).toBeDefined()
})
