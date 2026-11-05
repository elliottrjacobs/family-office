import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { Advisor } from "@/api/office"
import type { EngineStatus, ModelCatalog } from "@/api/runs"
import { LaunchPanel } from "@/components/launch-panel"

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.sessionStorage.clear()
})

const base: Advisor = {
  name: "lynch",
  description: "Score a stock.",
  group: "playbooks",
  tier: "balanced",
  default_context: "none",
  allowed_context: ["none", "household"],
  invocation: "implicit",
  args: "<subject>",
  deep: false,
  commands: ["score"],
  report_kind: "score",
}

const defaults = {
  claude: { model: "claude-sonnet-5-5", effort: "medium" as const, max_budget_usd: 2, enabled: true },
  codex: { model: "gpt-5.6-sol", effort: "high" as const, max_budget_usd: 2, enabled: true },
}

const catalog: ModelCatalog = {
  engines: {
    claude: {
      label: "Claude Code",
      efforts: ["low", "medium", "high"],
      models: [
        { id: "claude-fable-5-1", label: "Fable 5.1", recommended: true },
        { id: "claude-opus-5-5", label: "Opus 5.5" },
        { id: "claude-sonnet-5-5", label: "Sonnet 5.5" },
      ],
    },
    codex: {
      label: "Codex",
      efforts: ["low", "medium", "high"],
      models: [{ id: "gpt-5.6-sol", label: "GPT-5.6 Sol", recommended: true }],
    },
  },
  default: "claude",
  defaults,
}

const engines: EngineStatus[] = [
  { name: "claude", usable: true, version: "2.1.283", reason: null, message: null, defaults: defaults.claude },
  {
    name: "codex",
    usable: false,
    version: null,
    reason: "engine_disabled",
    message: "The codex engine is turned off in office.toml.",
    defaults: defaults.codex,
  },
]

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
}

/** /api/models answers with the catalog; a launch echoes a run; previews never settle. */
function stubFetch() {
  const fetch = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/models") return respond(catalog)
    if (path === "/api/runs" && init?.method === "POST") return respond({ id: "RUN" })
    return new Promise<Response>(() => {})
  })
  vi.stubGlobal("fetch", fetch)
  return fetch
}

function launched(fetch: ReturnType<typeof stubFetch>) {
  const call = fetch.mock.calls.find(([path, init]) => path === "/api/runs" && init?.method === "POST")
  return JSON.parse(String(call![1]!.body))
}

const group = (name: string) => within(screen.getByRole("radiogroup", { name }))

describe("LaunchPanel", () => {
  it("offers only the advisor's allowed levels and hides deep when undeclared", () => {
    stubFetch()
    render(<LaunchPanel advisor={base} deepAvailable={true} onLaunched={vi.fn()} />)
    const levels = group("Context level")
      .getAllByRole("radio")
      .map((r) => r.textContent)
    expect(levels).toEqual(["None", "Household"])
    expect(screen.queryByRole("switch")).toBeNull()
  })

  it("shows deep only when the advisor declares it and the runner allows it", () => {
    stubFetch()
    const research = { ...base, name: "research", deep: true, allowed_context: ["none", "household", "full"] as Advisor["allowed_context"] }
    const { rerender } = render(<LaunchPanel advisor={research} deepAvailable={true} onLaunched={vi.fn()} />)
    expect(group("Context level").getAllByRole("radio")).toHaveLength(3)
    expect(screen.getByRole("switch")).toBeTruthy()
    rerender(<LaunchPanel advisor={research} deepAvailable={false} onLaunched={vi.fn()} />)
    expect(screen.queryByRole("switch")).toBeNull()
  })

  it("starts from the office defaults and disables an unusable engine with its message", async () => {
    stubFetch()
    render(<LaunchPanel advisor={base} deepAvailable={false} engines={engines} officeDefault="claude" onLaunched={vi.fn()} />)
    const model = (await screen.findByLabelText("Model")) as HTMLSelectElement
    await waitFor(() => expect(model.value).toBe("claude-sonnet-5-5"))
    expect(group("Effort").getByRole("radio", { name: "Medium" }).getAttribute("aria-checked")).toBe("true")
    const claude = group("Engine").getByRole("radio", { name: "Claude Code" })
    const codex = group("Engine").getByRole("radio", { name: "Codex" }) as HTMLButtonElement
    expect(claude.getAttribute("aria-checked")).toBe("true")
    expect(codex.disabled).toBe(true)
    expect(screen.getByText(/Codex is unavailable: The codex engine is turned off/)).toBeTruthy()
    const options = Array.from(model.options).map((o) => o.value)
    expect(options).toEqual(["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "__other__"])
  })

  it("submits a free-text model and the chosen effort, and remembers them", async () => {
    const fetch = stubFetch()
    const onLaunched = vi.fn()
    render(<LaunchPanel advisor={base} deepAvailable={false} engines={engines} officeDefault="claude" onLaunched={onLaunched} />)
    const model = (await screen.findByLabelText("Model")) as HTMLSelectElement
    await waitFor(() => expect(model.value).toBe("claude-sonnet-5-5"))
    fireEvent.change(model, { target: { value: "__other__" } })
    fireEvent.change(screen.getByLabelText("Model id"), { target: { value: "claude-preview-6" } })
    fireEvent.click(group("Effort").getByRole("radio", { name: "High" }))
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "acme" } })
    fireEvent.click(screen.getByRole("button", { name: /Start/ }))
    await waitFor(() => expect(onLaunched).toHaveBeenCalled())
    expect(launched(fetch)).toEqual({
      skill: "lynch",
      subject: "ACME",
      level: "none",
      deep: false,
      engine: "claude",
      model: "claude-preview-6",
      effort: "high",
    })
    expect(JSON.parse(window.sessionStorage.getItem("fo.launch.v1.lynch")!)).toEqual({
      engine: "claude",
      model: "claude-preview-6",
      effort: "high",
    })
  })

  it("passes a curated model and effort and restores the last choice for the advisor", async () => {
    window.sessionStorage.setItem(
      "fo.launch.v1.lynch",
      JSON.stringify({ engine: "claude", model: "claude-opus-5-5", effort: "low" })
    )
    const fetch = stubFetch()
    const onLaunched = vi.fn()
    render(<LaunchPanel advisor={base} deepAvailable={false} engines={engines} officeDefault="claude" onLaunched={onLaunched} />)
    const model = (await screen.findByLabelText("Model")) as HTMLSelectElement
    await waitFor(() => expect(model.value).toBe("claude-opus-5-5"))
    expect(group("Effort").getByRole("radio", { name: "Low" }).getAttribute("aria-checked")).toBe("true")
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "BETA" } })
    fireEvent.click(screen.getByRole("button", { name: /Start/ }))
    await waitFor(() => expect(onLaunched).toHaveBeenCalled())
    expect(launched(fetch)).toMatchObject({ engine: "claude", model: "claude-opus-5-5", effort: "low" })
  })
})
