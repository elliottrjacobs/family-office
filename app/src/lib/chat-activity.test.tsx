import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import type { Run } from "@/api/runs"
import { useChatActivity } from "@/lib/chat-activity"

afterEach(cleanup)

const chat = (id: string, skill: string, status: Run["status"]) =>
  ({ id, skill, status, subject: "household", created: `2026-01-0${id}T00:00:00Z` }) as Run

function Activity({ list, open }: { list: Run[]; open: string | null }) {
  const { answering, finished } = useChatActivity(list, open)
  return (
    <p>
      answering {Object.keys(answering).sort().join(",") || "none"}; finished{" "}
      {Object.keys(finished).sort().join(",") || "none"}
    </p>
  )
}

describe("useChatActivity", () => {
  it("shows every advisor that is answering, then the ones that finished unseen", () => {
    const view = render(
      <Activity list={[chat("1", "tax", "running"), chat("2", "estate", "queued"), chat("3", "cio", "completed")]} open="2" />
    )
    // A chat that was already done when the page loaded is never marked.
    expect(screen.getByText("answering estate,tax; finished none")).toBeTruthy()
    view.rerender(
      <Activity
        list={[chat("1", "tax", "awaiting_input"), chat("2", "estate", "awaiting_input"), chat("3", "cio", "completed")]}
        open="2"
      />
    )
    // Estate finished on screen; Tax finished while the person was reading Estate.
    expect(screen.getByText("answering none; finished tax")).toBeTruthy()
    view.rerender(
      <Activity
        list={[chat("1", "tax", "awaiting_input"), chat("2", "estate", "awaiting_input"), chat("3", "cio", "completed")]}
        open="1"
      />
    )
    expect(screen.getByText("answering none; finished none")).toBeTruthy()
  })
})
