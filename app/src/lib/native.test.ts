import { afterEach, describe, expect, it, vi } from "vitest"

import { hasNative, native, stepButton, stepPlace } from "@/lib/native"

afterEach(() => {
  delete (window as unknown as { webkit?: unknown }).webkit
})

describe("native", () => {
  it("does nothing in a browser, where the Mac app's handler is absent", () => {
    expect(hasNative()).toBe(false)
    expect(native("setup")).toBe(false)
  })

  it("posts the action to the Mac app's handler", () => {
    const postMessage = vi.fn()
    ;(window as unknown as { webkit: unknown }).webkit = { messageHandlers: { familyOffice: { postMessage } } }
    expect(hasNative()).toBe(true)
    expect(native("settings:connectors")).toBe(true)
    expect(postMessage).toHaveBeenCalledWith({ action: "settings:connectors" })
  })

  it("maps setup steps to the window that does them", () => {
    expect(stepButton("connect:plaid")).toEqual({ action: "settings:connectors", label: "Open Connectors" })
    expect(stepButton("connect")?.action).toBe("settings:connectors")
    expect(stepButton("setup")).toEqual({ action: "setup", label: "Open setup" })
    // The interview and other steps are done on the page, not in a native window.
    expect(stepButton("onboard")).toBeNull()
    expect(stepButton(null)).toBeNull()
    expect(stepPlace("connect:simplefin")).toMatch(/Settings > Connectors/)
    expect(stepButton("connect:plaid")).toEqual({ action: "settings:connectors", label: "Open Connectors" })
    expect(stepPlace("onboard")).toBeNull()
  })
})
