import { act, cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { refreshAll, useApi } from "@/api/use-api"

afterEach(cleanup)

function Figure({ load }: { load: () => Promise<number> }) {
  const loaded = useApi("figure", load)
  return <p>{loaded.loading ? "loading" : `value ${loaded.data}`}</p>
}

describe("useApi", () => {
  it("refreshAll asks again for everything on screen, as after a sync", async () => {
    const load = vi.fn().mockResolvedValueOnce(1).mockResolvedValueOnce(2)
    render(<Figure load={load} />)
    await act(async () => {})
    expect(screen.getByText("value 1")).toBeTruthy()
    await act(async () => {
      refreshAll()
    })
    expect(screen.getByText("value 2")).toBeTruthy()
    expect(load).toHaveBeenCalledTimes(2)
  })

  it("a view that mounts again shows the last answer at once, with no loading state", async () => {
    const load = vi.fn().mockResolvedValue(7)
    const first = render(<Figure load={load} />)
    expect(screen.getByText("loading")).toBeTruthy()
    await act(async () => {})
    expect(screen.getByText("value 7")).toBeTruthy()
    first.unmount()
    // As when a tab is opened a second time: painted from memory on the first render.
    render(<Figure load={load} />)
    expect(screen.getByText("value 7")).toBeTruthy()
    expect(screen.queryByText("loading")).toBeNull()
    await act(async () => {})
    expect(load).toHaveBeenCalledTimes(1)
  })

  it("asks again once the remembered answer is no longer fresh, keeping it on screen meanwhile", async () => {
    vi.useFakeTimers()
    try {
      const load = vi.fn().mockResolvedValueOnce(1).mockResolvedValueOnce(2)
      const first = render(<Figure load={load} />)
      await act(async () => {})
      first.unmount()
      vi.advanceTimersByTime(5_000)
      render(<Figure load={load} />)
      expect(screen.getByText("value 1")).toBeTruthy()
      await act(async () => {})
      expect(screen.getByText("value 2")).toBeTruthy()
      expect(load).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it("two views asking for the same thing at once share one request", async () => {
    const load = vi.fn().mockResolvedValue(3)
    render(
      <>
        <Figure load={load} />
        <Figure load={load} />
      </>
    )
    await act(async () => {})
    expect(screen.getAllByText("value 3")).toHaveLength(2)
    expect(load).toHaveBeenCalledTimes(1)
  })
})
