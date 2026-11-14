import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { Run } from "@/api/runs"
import { byPeriod, ChatHistory, chatTitle, period } from "@/components/chat-history"

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const base: Run = {
  id: "01M50V918GZEEPD9WHWV3M7CH6",
  skill: "tax",
  subject: "household",
  mode: "chat",
  title: "Harvest losses before year end?",
  level: "full",
  deep: false,
  status: "awaiting_input",
  session_id: "s",
  report: "",
  report_written: false,
  decisions: [],
  verify: null,
  error: null,
  cost_usd: 0,
  created: new Date().toISOString(),
}

const older: Run = {
  ...base,
  id: "01M50V918GZEEPD9WHWV3M7CH7",
  mode: undefined,
  title: undefined,
  skill: "research",
  subject: "ACME",
  created: "2026-01-05T12:00:00Z",
}

describe("ChatHistory", () => {
  it("names a chat by its first message and an older report run by its subject", () => {
    expect(chatTitle(base)).toBe("Harvest losses before year end?")
    expect(chatTitle(older)).toBe("ACME report")
    expect(chatTitle({ ...older, subject: "household", skill: "cio" })).toBe("CIO report")
  })

  it("groups by day, newest first", () => {
    const now = new Date("2026-11-14T15:00:00")
    expect(period("2026-11-14T09:00:00", now)).toBe("Today")
    expect(period("2026-11-13T23:00:00", now)).toBe("Yesterday")
    expect(period("2026-11-10T09:00:00", now)).toBe("This week")
    expect(period("2026-09-02T09:00:00", now)).toBe("September 2026")
    const groups = byPeriod(
      [older, { ...base, created: "2026-11-14T09:00:00" }, { ...base, id: "X", created: "2026-11-14T11:00:00" }],
      now
    )
    expect(groups.map((g) => [g.label, g.runs.map((r) => r.id)])).toEqual([
      ["Today", ["X", base.id]],
      ["January 2026", [older.id]],
    ])
  })

  it("links each chat, marks the open one, and deletes after asking", async () => {
    const fetch = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ deleted: base.id }), { status: 200 })))
    vi.stubGlobal("fetch", fetch)
    const onDeleted = vi.fn()
    render(<ChatHistory runs={[base, older]} current={base.id} onDeleted={onDeleted} />)
    const open = screen.getByRole("link", { name: /Harvest losses/ })
    expect(open.getAttribute("href")).toBe(`/advisors/tax?chat=${base.id}`)
    expect(open.getAttribute("aria-current")).toBe("page")
    expect(screen.getByRole("link", { name: /ACME report/ }).getAttribute("href")).toBe(
      `/advisors/research?chat=${older.id}`
    )
    fireEvent.click(screen.getByRole("button", { name: "Delete chat: Harvest losses before year end?" }))
    const dialog = within(await screen.findByRole("dialog"))
    expect(dialog.getByText(/Reports it saved and decisions it recorded are kept/)).toBeTruthy()
    expect(fetch).not.toHaveBeenCalled()
    fireEvent.click(dialog.getByRole("button", { name: "Delete chat" }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(base.id))
    expect(fetch).toHaveBeenCalledWith(`/api/runs/${base.id}`, expect.objectContaining({ method: "DELETE" }))
  })

  it("a chat that is answering cannot be deleted, and an empty history says so", () => {
    const { unmount } = render(<ChatHistory runs={[{ ...base, status: "running" }]} onDeleted={vi.fn()} />)
    expect(screen.queryByRole("button", { name: /Delete chat/ })).toBeNull()
    expect(screen.getByLabelText("Answering")).toBeTruthy()
    unmount()
    render(<ChatHistory runs={[]} onDeleted={vi.fn()} empty="No chats with Tax yet." />)
    expect(screen.getByText("No chats with Tax yet.")).toBeTruthy()
  })
})
