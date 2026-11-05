import { describe, expect, it } from "vitest"

import {
  ADVISOR_IDS,
  advisorIdFor,
  defaultAppearance,
  glowColors,
  isDefault,
  luminance,
  mix,
  parseAppearance,
  serializeAppearance,
  SHAPE_IDS,
  SWATCHES,
  trimColors,
} from "@/avatars/appearance"
import { SHAPES } from "@/avatars/shapes"

// The cast table from the plan's avatar references.
const CAST = {
  cio: "#2F5BD3",
  cfo: "#E3A21A",
  planner: "#EF6650",
  tax: "#1F9D63",
  research: "#6457F0",
  diligence: "#5B6B7F",
  scout: "#7C9A2E",
  macro: "#0EA5B7",
  options: "#A94FD6",
  technicals: "#2C2F36",
  risk: "#E5484D",
  realestate: "#C8743E",
  ventures: "#E84593",
} as const

describe("defaultAppearance", () => {
  it.each(ADVISOR_IDS)("gives %s its cast shell, own shape and steel trim", (id) => {
    const look = defaultAppearance(id)
    expect(look.shell).toBe(CAST[id])
    expect(look.shape).toBe(id)
    expect(look.trim).toBe("steel")
    expect(look.screen).toBe("tinted")
    expect(look.finish).toBe("gloss")
    expect(look.accessory).toBe(true)
    expect(look.speed).toBe(1)
    expect(look.eyes).toBe(SHAPES[id].eyeKind)
  })

  it("covers all thirteen advisors and fourteen swatches", () => {
    expect(ADVISOR_IDS).toHaveLength(13)
    expect(SWATCHES).toHaveLength(14)
    expect(SHAPE_IDS).toHaveLength(22)
    for (const shape of SHAPE_IDS) expect(SHAPES[shape]).toBeDefined()
  })

  it("keeps the cast's antennas", () => {
    expect(defaultAppearance("cio").antenna).toBe("compass")
    expect(defaultAppearance("planner").antenna).toBe("flag")
    expect(defaultAppearance("scout").antenna).toBe("periscope")
    expect(defaultAppearance("options").antenna).toBe("twin")
    expect(defaultAppearance("risk").antenna).toBe("none")
  })
})

describe("parseAppearance", () => {
  it.each(ADVISOR_IDS)("round-trips the %s default through JSON unchanged", (id) => {
    const look = defaultAppearance(id)
    const text = JSON.stringify(look)
    expect(parseAppearance(JSON.parse(text), id)).toEqual(look)
    expect(parseAppearance(serializeAppearance(look), id)).toEqual(look)
  })

  it("ignores unknown fields and defaults a missing trim", () => {
    const stored = { ...defaultAppearance("tax"), shell: "#E84593", sparkle: true } as Record<string, unknown>
    delete stored.trim
    const look = parseAppearance(stored, "tax")
    expect(look.trim).toBe("steel")
    expect(look.shell).toBe("#E84593")
    expect(look).not.toHaveProperty("sparkle")
  })

  it("keeps a custom hex outside the swatches", () => {
    const look = parseAppearance(
      { ...defaultAppearance("cio"), shell: "#123abc", trim: "#a0b0c0", screen: "#ff00aa" },
      "cio",
    )
    expect(look.shell).toBe("#123ABC")
    expect(look.trim).toBe("#A0B0C0")
    expect(look.screen).toBe("#FF00AA")
    expect(SWATCHES.map((s) => s.hex)).not.toContain(look.shell)
  })

  it("replaces each invalid field with the default and clamps speed", () => {
    const look = parseAppearance(
      { shape: "blob", shell: "blue", trim: "gold", eyes: "laser", antenna: 3, accessory: "yes", speed: 9 },
      "risk",
    )
    const fallback = defaultAppearance("risk")
    expect(look).toEqual({ ...fallback, speed: 2 })
    expect(parseAppearance({ speed: -1 }, "risk").speed).toBe(0)
    expect(parseAppearance({ speed: Number.NaN }, "risk").speed).toBe(1)
  })

  it("returns the default for garbage, arrays, bad JSON and future versions", () => {
    for (const input of [null, 42, "not json", "[]", [], { ...defaultAppearance("cfo"), version: 2 }]) {
      expect(parseAppearance(input, "cfo")).toEqual(defaultAppearance("cfo"))
    }
  })

  it("accepts every shape for any advisor", () => {
    for (const shape of SHAPE_IDS) expect(parseAppearance({ shape }, "macro").shape).toBe(shape)
  })
})

describe("isDefault", () => {
  it("is true for the default and false after any change", () => {
    expect(isDefault(defaultAppearance("ventures"), "ventures")).toBe(true)
    expect(isDefault({ ...defaultAppearance("ventures"), finish: "matte" }, "ventures")).toBe(false)
    expect(isDefault(defaultAppearance("cio"), "ventures")).toBe(false)
  })
})

describe("advisorIdFor", () => {
  it("maps the plan skill to the planner and keeps other advisor ids", () => {
    expect(advisorIdFor("plan")).toBe("planner")
    expect(advisorIdFor("cio")).toBe("cio")
    expect(advisorIdFor("realestate")).toBe("realestate")
    expect(advisorIdFor("journal")).toBeNull()
  })
})

describe("colour helpers", () => {
  it("mixes per channel and measures luminance", () => {
    expect(mix("#000000", "#FFFFFF", 0.5)).toBe("#808080")
    expect(mix("#2F5BD3", "#FFFFFF", 0)).toBe("#2F5BD3")
    expect(mix("#2F5BD3", "#000000", 1)).toBe("#000000")
    expect(luminance("#FFFFFF")).toBe(1)
    expect(luminance("#000000")).toBe(0)
  })

  it("glows mint on dark shells and tints light ones toward white", () => {
    expect(glowColors(defaultAppearance("technicals")).eye).toBe("#7CFFB2")
    expect(glowColors(defaultAppearance("cio")).eye).toBe(mix("#2F5BD3", "#FFFFFF", 0.62))
    expect(glowColors({ ...defaultAppearance("cio"), screen: "amber" }).eye).toBe("#FFC46B")
    expect(glowColors({ ...defaultAppearance("cio"), screen: "#112233" }).eye).toBe("#112233")
  })

  it("derives the steel stem colour of the cast", () => {
    expect(trimColors("steel")).toEqual({ light: "#EEF1F5", dark: "#98A2B0", stem: "#A9B2BE" })
    expect(trimColors("#808080").light).toBe(mix("#808080", "#FFFFFF", 0.45))
  })
})
