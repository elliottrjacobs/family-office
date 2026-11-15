import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { Run, RunEvent } from "@/api/runs"
import { RunEngine, RunView } from "@/components/run-view"
import { apply, empty } from "@/lib/transcript"

afterEach(cleanup)

const run: Run = {
  id: "01M50V918GZEEPD9WHWV3M7CH6",
  skill: "research",
  subject: "ACME",
  level: "none",
  deep: false,
  status: "completed",
  session_id: "s",
  report: "reports/research/ACME/2026-11-05-report.md",
  report_written: true,
  decisions: [],
  verify: { valid: true, reason: null },
  error: null,
  cost_usd: 0.1,
  created: "2026-11-05T00:00:00Z",
  engine: "claude",
  model: "claude-fable-5-1",
  effort: "high",
  web: true,
  web_count: 3,
}

const chat: Run = {
  ...run,
  skill: "tax",
  subject: "household",
  mode: "chat",
  title: "What is the 2026 401(k) limit?",
  level: "full",
  status: "awaiting_input",
  report: "",
  report_written: false,
  verify: null,
}

// A recorded stream: one search and two fetches folded in from the guard's web log.
const events: RunEvent[] = [
  { seq: 1, kind: "user", text: "/research ACME --level none" },
  { seq: 2, kind: "init", session_id: "s", model: "m", tools: ["Bash", "WebSearch", "WebFetch"] },
  { seq: 3, kind: "web", action: "search", value: "ACME 10-K 2026" },
  { seq: 4, kind: "web", action: "fetch", value: "https://www.sec.gov/cgi-bin/browse-edgar?company=acme" },
  { seq: 5, kind: "web", action: "fetch", value: "javascript:alert(1)" },
  { seq: 6, kind: "text", text: "Done." },
  { seq: 7, kind: "status", status: "completed" },
]

function view(record: Run | undefined, list: RunEvent[], pending?: string) {
  const transcript = list.reduce(apply, empty)
  const onNew = vi.fn()
  render(
    <>
      {record && <RunEngine run={record} visits={transcript.web.length} />}
      <RunView run={record} transcript={transcript} decisions={[]} pending={pending} onResume={vi.fn()} onNew={onNew} />
    </>
  )
  return onNew
}

describe("RunView", () => {
  it("lists what was looked up: searches as queries, pages as links by hostname", () => {
    view(run, events)
    fireEvent.click(screen.getByRole("button", { name: /Looked up on the web \(3\)/ }))
    const rows = within(screen.getByRole("list", { name: "Sites visited" })).getAllByRole("listitem")
    expect(rows.map((r) => r.textContent)).toEqual(["Searched “ACME 10-K 2026”", "www.sec.gov", "javascript:alert(1)"])
    const link = screen.getByRole("link", { name: "www.sec.gov" })
    expect(link.getAttribute("href")).toBe("https://www.sec.gov/cgi-bin/browse-edgar?company=acme")
    expect(link.getAttribute("title")).toBe("https://www.sec.gov/cgi-bin/browse-edgar?company=acme")
    // Only web addresses become links.
    expect(screen.queryByRole("link", { name: /javascript/ })).toBeNull()
    expect(screen.getByLabelText("Engine and model").textContent).toContain("3 web visits")
  })

  it("shows no lookups and no count for a run without web access", () => {
    view({ ...run, level: "household", web: false, web_count: 0 }, events.filter((e) => e.kind !== "web"))
    expect(screen.queryByRole("button", { name: /Looked up on the web/ })).toBeNull()
    expect(screen.getByLabelText("Engine and model").textContent).not.toContain("web")
  })

  it("a report run shows its invocation and its report; a chat shows the words typed", () => {
    view(run, events)
    expect(screen.getByText("/research ACME --level none")).toBeTruthy()
    expect(screen.getByRole("link", { name: /Open report/ })).toBeTruthy()
    cleanup()
    view(chat, [
      { seq: 1, kind: "user", text: "/slash looks like a command but is what I typed" },
      { seq: 2, kind: "text", text: "The limit is in the notice." },
      { seq: 3, kind: "status", status: "awaiting_input" },
    ])
    expect(screen.getByText("/slash looks like a command but is what I typed").className).toContain("rounded-2xl")
    expect(screen.queryByText(/Started/)).toBeNull()
    // A plain answer needs no note under it.
    expect(screen.queryByText(/waiting for your reply/)).toBeNull()
    expect(screen.queryByRole("link", { name: /Open report/ })).toBeNull()
    expect(screen.getByLabelText("Engine and model").textContent).toContain("Full profile")
  })

  it("shows a message just sent, and that the advisor is thinking, before the stream answers", () => {
    view(undefined, [], "Can we afford the house?")
    expect(screen.getByText("Can we afford the house?")).toBeTruthy()
    expect(screen.getByRole("status").textContent).toBe("Thinking…")
  })

  it("a failed turn says why and how to go on", () => {
    const failed: Run = { ...chat, status: "failed", error: { reason: "x", message: "The advisor ended without an answer." } }
    const stream: RunEvent[] = [
      { seq: 1, kind: "user", text: "Hello" },
      { seq: 2, kind: "status", status: "failed" },
    ]
    view(failed, stream)
    expect(screen.getByRole("alert").textContent).toBe(
      "The advisor ended without an answer. Send a message to try again."
    )
    cleanup()
    const onNew = view({ ...failed, session_id: null }, stream)
    fireEvent.click(screen.getByRole("button", { name: "New chat" }))
    expect(onNew).toHaveBeenCalled()
  })
})
