import { afterEach, describe, expect, it, vi } from "vitest"

import { defaultAppearance } from "@/avatars/appearance"
import { loadAppearance, resetAppearance, saveAppearance, storageKey, subscribe } from "@/avatars/store"

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe("avatar store", () => {
  it("saves under a versioned key per advisor and loads it back", () => {
    const look = { ...defaultAppearance("scout"), shell: "#E84593", eyes: "ring" as const }
    expect(saveAppearance("scout", look)).toBe(true)
    expect(storageKey("scout")).toBe("fo.avatar.v1.scout")
    expect(JSON.parse(window.localStorage.getItem("fo.avatar.v1.scout") ?? "{}")).toEqual(look)
    expect(loadAppearance("scout")).toEqual(look)
    expect(loadAppearance("cio")).toEqual(defaultAppearance("cio"))
  })

  it("returns the same object while the stored text is unchanged", () => {
    saveAppearance("cfo", { ...defaultAppearance("cfo"), finish: "matte" })
    expect(loadAppearance("cfo")).toBe(loadAppearance("cfo"))
  })

  it("resets to the default", () => {
    saveAppearance("tax", { ...defaultAppearance("tax"), trim: "brass" })
    expect(resetAppearance("tax")).toBe(true)
    expect(window.localStorage.getItem("fo.avatar.v1.tax")).toBeNull()
    expect(loadAppearance("tax")).toEqual(defaultAppearance("tax"))
  })

  it("returns the default for a corrupted entry", () => {
    window.localStorage.setItem("fo.avatar.v1.risk", "{not json")
    expect(loadAppearance("risk")).toEqual(defaultAppearance("risk"))
  })

  it("returns the default and never throws when storage is blocked", () => {
    saveAppearance("macro", { ...defaultAppearance("macro"), shell: "#E5484D" })
    const blocked = () => {
      throw new DOMException("blocked", "SecurityError")
    }
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(blocked)
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked)
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(blocked)
    expect(loadAppearance("macro")).toEqual(defaultAppearance("macro"))
    expect(saveAppearance("macro", defaultAppearance("macro"))).toBe(false)
    expect(resetAppearance("macro")).toBe(false)
  })

  it("notifies only the advisor's subscribers on save and reset", () => {
    const planner = vi.fn()
    const cio = vi.fn()
    const stop = subscribe("planner", planner)
    subscribe("cio", cio)
    saveAppearance("planner", { ...defaultAppearance("planner"), antenna: "none" })
    resetAppearance("planner")
    expect(planner).toHaveBeenCalledTimes(2)
    expect(cio).not.toHaveBeenCalled()
    stop()
    saveAppearance("planner", defaultAppearance("planner"))
    expect(planner).toHaveBeenCalledTimes(2)
  })
})
