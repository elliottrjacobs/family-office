import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { Advisor } from "@/api/office"
import type { Run } from "@/api/runs"
import { AdvisorPage, starters } from "@/views/advisor"

const estate: Advisor = {
  name: "estate",
  description:
    "Find gaps in estate and continuity readiness: wills, trusts, beneficiaries. Use for 'are we prepared if something happens', 'beneficiary check', or preparing questions for counsel.",
  group: "specialists",
  tier: "strong",
  default_context: "full",
  allowed_context: ["none", "household", "full"],
  invocation: "implicit",
  args: "<subject>",
  deep: false,
  commands: ["doctor"],
  report_kind: "estate",
}
const onboard: Advisor = {
  ...estate,
  name: "onboard",
  group: "routine",
  description: "Guided first-time setup interview. Use for 'set up my office', 'get started'.",
  report_kind: "onboard",
}

const app = vi.hoisted(() => ({
  registry: { skills: [] as unknown[], agents: [] },
  status: { chat: true, app: true },
  refresh: () => {},
}))
vi.mock("@/app-data", () => ({ useAppData: () => app }))

const defaults = { model: "claude-fable-5-2", effort: "high", max_budget_usd: 2, enabled: true }
const started: Run = {
  id: "01M50V918GZEEPD9WHWV3M7CH6",
  skill: "estate",
  subject: "household",
  mode: "chat",
  title: "Are we prepared?",
  level: "full",
  deep: false,
  status: "queued",
  session_id: null,
  report: "",
  report_written: false,
  decisions: [],
  verify: null,
  error: null,
  cost_usd: 0,
  created: new Date().toISOString(),
  engine: "claude",
  web: true,
  web_wanted: null,
}

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
}

let history: Run[] = []
let policy = "on"

function stubServer() {
  const fetch = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/runs" && init?.method === "POST") {
      const body = JSON.parse(String(init.body))
      return respond({ ...started, skill: body.skill })
    }
    if (path === "/api/runs") return respond(history)
    if (path.startsWith("/api/runs/")) return respond(history.find((r) => path.endsWith(r.id)) ?? started)
    if (path === "/api/runner") {
      return respond({
        ready: true,
        default: "claude",
        deep: true,
        web: policy,
        engines: [{ name: "claude", usable: true, version: "2.1.283", reason: null, message: null, defaults }],
      })
    }
    if (path === "/api/models") {
      return respond({
        engines: { claude: { label: "Claude Code", efforts: ["low", "medium", "high"], models: [{ id: "claude-fable-5-2", label: "Fable 5.2" }] } },
        default: "claude",
        defaults: { claude: defaults },
      })
    }
    if (path === "/api/reports") return respond({ reports: [], parse_errors: [] })
    if (path === "/api/decisions") return respond([])
    return respond({})
  })
  vi.stubGlobal("fetch", fetch)
  return fetch
}

class Stream {
  onmessage: ((message: { data: string }) => void) | null = null
  addEventListener() {}
  close() {}
}

beforeEach(() => {
  history = []
  policy = "on"
  app.registry.skills = [estate, onboard]
  vi.stubGlobal("EventSource", Stream)
  window.history.replaceState(null, "", "/advisors/estate")
  window.sessionStorage.clear()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const posted = (fetch: ReturnType<typeof stubServer>) =>
  JSON.parse(String(fetch.mock.calls.find(([path, init]) => path === "/api/runs" && init?.method === "POST")![1]!.body))

async function page(name = "estate") {
  const fetch = stubServer()
  await act(async () => {
    render(<AdvisorPage name={name} />)
  })
  await screen.findByRole("textbox", { name: "Message" })
  return fetch
}

describe("AdvisorPage", () => {
  it("opens as a chat: a free message box and suggestions from the advisor, no subject or ticker", async () => {
    await page()
    expect(screen.getByRole("heading", { name: "Ask Estate" })).toBeTruthy()
    const box = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement
    expect(box.placeholder).toBe("Message Estate")
    expect(screen.queryByLabelText("Subject")).toBeNull()
    expect(document.body.textContent).not.toMatch(/ticker/i)
    const suggestions = within(screen.getByRole("list", { name: "Suggestions" })).getAllByRole("button")
    expect(suggestions.map((b) => b.textContent)).toEqual(["Are we prepared if something happens", "Beneficiary check"])
    expect(starters(estate)).toHaveLength(2)
    fireEvent.click(suggestions[1])
    expect(box.value).toBe("Beneficiary check")
  })

  it("sends the message as typed, with web on by default, and opens the new chat", async () => {
    const fetch = await page()
    const box = screen.getByRole("textbox", { name: "Message" })
    expect(screen.getByRole("button", { name: "Web search" }).getAttribute("aria-pressed")).toBe("true")
    fireEvent.change(box, { target: { value: "Are we prepared?" } })
    await act(async () => {
      fireEvent.keyDown(box, { key: "Enter" })
    })
    await waitFor(() => expect(window.location.search).toBe(`?chat=${started.id}`))
    expect(posted(fetch)).toEqual({
      skill: "estate",
      message: "Are we prepared?",
      level: "full",
      deep: false,
      engine: "claude",
      model: "claude-fable-5-2",
      effort: "high",
    })
  })

  it("the web switch turns web off for the chat", async () => {
    const fetch = await page()
    fireEvent.click(screen.getByRole("button", { name: "Web search" }))
    const box = screen.getByRole("textbox", { name: "Message" })
    fireEvent.change(box, { target: { value: "Offline, please." } })
    await act(async () => {
      fireEvent.keyDown(box, { key: "Enter" })
    })
    await waitFor(() => expect(posted(fetch).web).toBe(false))
  })

  it("an office that isolates web says why it is off in a chat that reads the household", async () => {
    policy = "isolated"
    await page()
    const toggle = (await screen.findByRole("button", { name: "Web search" })) as HTMLButtonElement
    await waitFor(() => expect(toggle.disabled).toBe(true))
    expect(toggle.title).toMatch(/only in chats that read no household data/)
  })

  it("lists earlier chats with this advisor only, and another advisor answering does not block sending", async () => {
    history = [
      { ...started, id: "01M50V918GZEEPD9WHWV3M7CH7", status: "awaiting_input", title: "Beneficiaries on the IRA" },
      { ...started, id: "01M50V918GZEEPD9WHWV3M7CH8", skill: "tax", status: "running", title: "Roth conversion" },
    ]
    const fetch = await page()
    const list = within(await screen.findByRole("navigation", { name: "Chat history" }))
    expect(list.getByRole("link", { name: /Beneficiaries on the IRA/ })).toBeTruthy()
    expect(list.queryByText("Roth conversion")).toBeNull()
    expect(screen.queryByText(/One advisor works at a time/)).toBeNull()
    const box = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement
    expect(box.disabled).toBe(false)
    fireEvent.change(box, { target: { value: "Who inherits the house?" } })
    await act(async () => {
      fireEvent.keyDown(box, { key: "Enter" })
    })
    await waitFor(() => expect(posted(fetch).message).toBe("Who inherits the house?"))
  })

  it("Onboard interviews in the app: one button starts it, and nothing mentions a terminal", async () => {
    window.history.replaceState(null, "", "/advisors/onboard")
    const fetch = await page("onboard")
    expect(screen.getByRole("heading", { name: "Let's set up your office" })).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/terminal|coding agent/i)
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start the interview" }))
    })
    await waitFor(() => expect(posted(fetch)).toMatchObject({ skill: "onboard", message: "Let's set up my office." }))
  })
})
