import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { Decision } from "@/api/office"
import { RecordDecision, Reopen, Verdict } from "@/components/decision-actions"

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const decision: Decision = {
  id: "01M50V918GZEEPD9WHWV3M7CH6",
  date: "2026-10-15",
  subject: "ACME",
  action: "HOLD",
  thesis: "Durable franchise.",
  invalidate: "Margins fall.",
  when: [],
  conviction: "HIGH",
  source: "research",
  report: null,
  context_level: "household",
  status: "open",
}

function respond(status: number, body: unknown) {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))
  vi.stubGlobal("fetch", fetch)
  return fetch
}

describe("Verdict", () => {
  it("names the rollback and closes the decision", async () => {
    const fetch = respond(200, { id: decision.id, event: "closed", outcome: "hit" })
    const done = vi.fn()
    render(<Verdict decision={decision} onDone={done} />)
    fireEvent.click(screen.getByRole("button", { name: "Hit" }))
    expect(await screen.findByText(/reopen it with a reason/i)).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/note/i), { target: { value: "Played out." } })
    fireEvent.click(screen.getByRole("button", { name: "Close as hit" }))
    await waitFor(() => expect(done).toHaveBeenCalled())
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe(`/api/decisions/${decision.id}/close`)
    expect(JSON.parse(init.body)).toEqual({ outcome: "hit", note: "Played out." })
  })

  it("explains a conflict when another tab closed it first", async () => {
    respond(409, { reason: "invalid_transition", message: "Close an open decision." })
    const done = vi.fn()
    render(<Verdict decision={decision} onDone={done} />)
    fireEvent.click(screen.getByRole("button", { name: "Miss" }))
    fireEvent.click(await screen.findByRole("button", { name: "Close as miss" }))
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("already closed")
    )
    expect(done).not.toHaveBeenCalled()
  })
})

describe("Reopen", () => {
  it("requires a reason", async () => {
    const fetch = respond(200, {})
    render(<Reopen decision={{ ...decision, status: "closed", outcome: "hit" }} onDone={vi.fn()} />)
    fireEvent.click(screen.getByRole("button", { name: "Reopen" }))
    const submit = await screen.findByRole("button", { name: "Reopen decision" })
    expect(submit).toHaveProperty("disabled", true)
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "New evidence." } })
    fireEvent.click(submit)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ reason: "New evidence." })
  })
})

describe("RecordDecision", () => {
  it("requires subject, action, thesis, invalidation, and conviction", async () => {
    const fetch = respond(200, { id: "x" })
    render(<RecordDecision onDone={vi.fn()} />)
    fireEvent.click(screen.getByRole("button", { name: "Record a decision" }))
    fireEvent.click(await screen.findByRole("button", { name: "Record decision" }))
    for (const field of ["subject", "action", "thesis", "invalidation", "conviction"]) {
      expect(screen.getByText(new RegExp(`${field} is required`, "i"))).toBeTruthy()
    }
    expect(fetch).not.toHaveBeenCalled()
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("sends the decision with its conditions", async () => {
    const fetch = respond(200, { id: "x" })
    const done = vi.fn()
    render(<RecordDecision onDone={done} />)
    fireEvent.click(screen.getByRole("button", { name: "Record a decision" }))
    fireEvent.change(await screen.findByLabelText(/^subject/i), { target: { value: "acme" } })
    fireEvent.change(screen.getByLabelText(/^action/i), { target: { value: "TRIM" } })
    fireEvent.change(screen.getByLabelText(/^thesis/i), { target: { value: "Too large." } })
    fireEvent.change(screen.getByLabelText(/^invalidate if/i), { target: { value: "Weight falls." } })
    fireEvent.change(screen.getByLabelText(/^conditions/i), { target: { value: "weight < 0.2\n\n" } })
    fireEvent.click(screen.getByRole("radio", { name: "Low" }))
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }))
    await waitFor(() => expect(done).toHaveBeenCalled())
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      subject: "ACME",
      action: "TRIM",
      thesis: "Too large.",
      invalidate: "Weight falls.",
      conviction: "LOW",
      context_level: "none",
      when: ["weight < 0.2"],
    })
  })
})
