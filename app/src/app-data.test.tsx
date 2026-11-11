import { act, cleanup, render } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"

import { onboarding } from "@/api/office"
import { AppDataProvider } from "@/app-data"

vi.mock("@/api/events", () => ({ subscribe: () => () => {} }))
vi.mock("@/api/office", () => ({
  onboarding: vi.fn(),
  status: vi.fn().mockResolvedValue({ mode: "onboarding" }),
  skills: vi.fn().mockResolvedValue({}),
  review: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

it("polls setup quickly, slows when ready, and resumes quickly when stale", async () => {
  vi.useFakeTimers()
  const load = vi.mocked(onboarding)
  load.mockResolvedValue({ state: "unconnected" } as Awaited<ReturnType<typeof onboarding>>)
  await act(async () => { render(<AppDataProvider>Test</AppDataProvider>) })
  expect(load).toHaveBeenCalledTimes(1)
  load.mockResolvedValue({ state: "ready" } as Awaited<ReturnType<typeof onboarding>>)
  await act(async () => { await vi.advanceTimersByTimeAsync(4_000) })
  expect(load).toHaveBeenCalledTimes(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(29_999) })
  expect(load).toHaveBeenCalledTimes(2)
  load.mockResolvedValue({ state: "stale" } as Awaited<ReturnType<typeof onboarding>>)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(load).toHaveBeenCalledTimes(3)
  await act(async () => { await vi.advanceTimersByTimeAsync(4_000) })
  expect(load).toHaveBeenCalledTimes(4)
})
