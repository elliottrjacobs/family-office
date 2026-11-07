import { cleanup, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { Run, RunEvent } from "@/api/runs"
import { RunView } from "@/components/run-view"
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

// A recorded stream: one search and two fetches folded in from the guard's web log.
const events: RunEvent[] = [
  { seq: 1, kind: "user", text: "/research ACME --level none" },
  { seq: 2, kind: "init", session_id: "s", model: "m", tools: ["Bash", "WebSearch", "WebFetch"] },
  { seq: 3, kind: "web", action: "search", value: "ACME 10-K 2026" },
  { seq: 4, kind: "web", action: "fetch", value: "https://www.sec.gov/cgi-bin/browse-edgar?company=acme" },
  { seq: 5, kind: "web", action: "fetch", value: "https://investors.example.com/annual" },
  { seq: 6, kind: "text", text: "Done." },
  { seq: 7, kind: "status", status: "completed" },
]

function view(record: Run, list: RunEvent[]) {
  const transcript = list.reduce(apply, empty)
  render(
    <RunView
      run={record}
      transcript={transcript}
      decisions={[]}
      onReply={vi.fn(async () => {})}
      onCancel={vi.fn(async () => {})}
      onNew={vi.fn()}
    />
  )
}

describe("RunView", () => {
  it("lists sites visited: searches as queries, fetches as hostnames with the URL on hover", () => {
    view(run, events)
    const sites = within(screen.getByRole("region", { name: "Sites visited (3)" }))
    const rows = sites.getAllByRole("listitem")
    expect(rows.map((r) => r.textContent)).toEqual([
      "Searched “ACME 10-K 2026”",
      "www.sec.gov",
      "investors.example.com",
    ])
    expect(sites.getByText("www.sec.gov").getAttribute("title")).toBe(
      "https://www.sec.gov/cgi-bin/browse-edgar?company=acme"
    )
    expect(screen.getByLabelText("Engine and model").textContent).toContain("3 web visits")
  })

  it("shows no sites and no count for a run without web access", () => {
    view({ ...run, level: "household", web: false, web_count: 0 }, events.filter((e) => e.kind !== "web"))
    expect(screen.queryByRole("region", { name: /Sites visited/ })).toBeNull()
    expect(screen.getByLabelText("Engine and model").textContent).not.toContain("web")
  })
})
