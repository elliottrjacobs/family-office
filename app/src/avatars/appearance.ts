// The appearance of an advisor robot: one typed, JSON-serializable config per advisor.
// Every option composes with every other; the renderer never assumes a pairing.

import { SHAPES } from "@/avatars/shapes"

export const ADVISOR_IDS = [
  "cio",
  "cfo",
  "planner",
  "tax",
  "research",
  "diligence",
  "scout",
  "macro",
  "options",
  "technicals",
  "risk",
  "realestate",
  "ventures",
] as const
export type AdvisorId = (typeof ADVISOR_IDS)[number]

export const GENERIC_SHAPES = [
  "rounded",
  "square",
  "capsule",
  "circle",
  "hexagon",
  "dome",
  "wide",
  "house",
  "rocket",
] as const
export const SHAPE_IDS = [...ADVISOR_IDS, ...GENERIC_SHAPES] as const
export type Shape = (typeof SHAPE_IDS)[number]

export const TRIM_PRESETS = ["steel", "silver", "brass", "copper", "black"] as const
export type TrimPreset = (typeof TRIM_PRESETS)[number]
export const SCREEN_PRESETS = ["tinted", "white", "mint", "amber"] as const
export type ScreenPreset = (typeof SCREEN_PRESETS)[number]
export const FINISHES = ["gloss", "matte"] as const
export type Finish = (typeof FINISHES)[number]
export const ANTENNAS = ["none", "ball", "compass", "flag", "periscope", "twin"] as const
export type Antenna = (typeof ANTENNAS)[number]
export const EYE_KINDS = ["pill", "dot", "square", "ring", "bar"] as const
export type EyeKind = (typeof EYE_KINDS)[number]
export const STATES = [
  "idle",
  "thinking",
  "reading",
  "writing",
  "speaking",
  "done",
  "error",
  "sleeping",
] as const
export type RobotState = (typeof STATES)[number]

/** A `#RRGGBB` string. Shorthand and alpha forms are not accepted. */
export type Hex = string

export type Appearance = {
  version: 1
  shape: Shape
  shell: Hex
  trim: TrimPreset | Hex
  screen: ScreenPreset | Hex
  finish: Finish
  antenna: Antenna
  accessory: boolean
  eyes: EyeKind
  speed: number
}

export const SPEED = { min: 0, max: 2, default: 1 } as const

/** The fourteen shell swatches of the cast, in picker order. */
export const SWATCHES: readonly { name: string; hex: Hex }[] = [
  { name: "Cobalt", hex: "#2F5BD3" },
  { name: "Sky", hex: "#2E9CEB" },
  { name: "Teal", hex: "#0EA5B7" },
  { name: "Green", hex: "#1F9D63" },
  { name: "Olive", hex: "#7C9A2E" },
  { name: "Gold", hex: "#E3A21A" },
  { name: "Orange", hex: "#F07A2B" },
  { name: "Coral", hex: "#EF6650" },
  { name: "Red", hex: "#E5484D" },
  { name: "Pink", hex: "#E84593" },
  { name: "Purple", hex: "#A94FD6" },
  { name: "Indigo", hex: "#6457F0" },
  { name: "Slate", hex: "#5B6B7F" },
  { name: "Graphite", hex: "#2C2F36" },
]

/** Trim metals: the top and bottom stops of the vertical trim gradient. */
export const TRIMS: Record<TrimPreset, { name: string; light: Hex; dark: Hex }> = {
  steel: { name: "Steel", light: "#EEF1F5", dark: "#98A2B0" },
  silver: { name: "Silver", light: "#FAFBFC", dark: "#B4BAC4" },
  brass: { name: "Brass", light: "#F7E4A6", dark: "#B08A3A" },
  copper: { name: "Copper", light: "#F6C7A6", dark: "#A85E38" },
  black: { name: "Black", light: "#5C616B", dark: "#1C1E23" },
}

/** Screen glows: `eye` paints the crisp eyes, `halo` the blurred glow behind them. */
export const SCREENS: Record<ScreenPreset, { name: string; eye: Hex | null; halo: Hex | null }> = {
  tinted: { name: "Tinted", eye: null, halo: null },
  white: { name: "White", eye: "#F4F8FF", halo: "#BFD6FF" },
  mint: { name: "Mint", eye: "#7CFFB2", halo: "#7CFFB2" },
  amber: { name: "Amber", eye: "#FFC46B", halo: "#FFB347" },
}

/** Colour derivation constants shared by the renderer. */
export const TONE = {
  mint: "#7CFFB2",
  darkShell: 0.25,
  glowTowardWhite: 0.62,
  customTrimLight: 0.45,
  customTrimDark: 0.15,
  trimStem: 0.8,
} as const

export const ADVISORS: Record<AdvisorId, { name: string; shell: Hex; antenna: Antenna }> = {
  cio: { name: "CIO", shell: "#2F5BD3", antenna: "compass" },
  cfo: { name: "CFO", shell: "#E3A21A", antenna: "none" },
  planner: { name: "Planner", shell: "#EF6650", antenna: "flag" },
  tax: { name: "Tax", shell: "#1F9D63", antenna: "none" },
  research: { name: "Research", shell: "#6457F0", antenna: "ball" },
  diligence: { name: "Diligence", shell: "#5B6B7F", antenna: "none" },
  scout: { name: "Scout", shell: "#7C9A2E", antenna: "periscope" },
  macro: { name: "Macro", shell: "#0EA5B7", antenna: "ball" },
  options: { name: "Options", shell: "#A94FD6", antenna: "twin" },
  technicals: { name: "Technicals", shell: "#2C2F36", antenna: "none" },
  risk: { name: "Risk", shell: "#E5484D", antenna: "none" },
  realestate: { name: "Real estate", shell: "#C8743E", antenna: "none" },
  ventures: { name: "Ventures", shell: "#E84593", antenna: "none" },
}

/** Skill names that differ from advisor ids. */
const SKILL_ALIASES: Record<string, AdvisorId> = { plan: "planner" }

/** The advisor id for a skill name (`plan` is the planner), or null when the skill has no robot. */
export function advisorIdFor(skillName: string): AdvisorId | null {
  const id = SKILL_ALIASES[skillName] ?? skillName
  return isAdvisorId(id) ? id : null
}

export function isAdvisorId(value: unknown): value is AdvisorId {
  return typeof value === "string" && (ADVISOR_IDS as readonly string[]).includes(value)
}

export function defaultAppearance(advisorId: AdvisorId): Appearance {
  const advisor = ADVISORS[advisorId]
  return {
    version: 1,
    shape: advisorId,
    shell: advisor.shell,
    trim: "steel",
    screen: "tinted",
    finish: "gloss",
    antenna: advisor.antenna,
    accessory: true,
    eyes: SHAPES[advisorId].eyeKind,
    speed: SPEED.default,
  }
}

const KEYS: readonly (keyof Appearance)[] = [
  "version",
  "shape",
  "shell",
  "trim",
  "screen",
  "finish",
  "antenna",
  "accessory",
  "eyes",
  "speed",
]

/** JSON with a fixed key order, so equal appearances serialize identically. */
export function serializeAppearance(appearance: Appearance): string {
  return JSON.stringify(Object.fromEntries(KEYS.map((key) => [key, appearance[key]])))
}

/**
 * Reads a stored config (an object or its JSON text). Unknown fields are ignored and
 * every missing or invalid field falls back to the advisor's default; a config from a
 * future version is not guessed at and yields the default.
 */
export function parseAppearance(input: unknown, advisorId: AdvisorId): Appearance {
  const fallback = defaultAppearance(advisorId)
  let value = input
  if (typeof value === "string") {
    try {
      value = JSON.parse(value)
    } catch {
      return fallback
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return fallback
  const raw = value as Record<string, unknown>
  if (raw.version !== undefined && raw.version !== 1) return fallback
  return {
    version: 1,
    shape: oneOf(raw.shape, SHAPE_IDS) ?? fallback.shape,
    shell: hexOf(raw.shell) ?? fallback.shell,
    trim: oneOf(raw.trim, TRIM_PRESETS) ?? hexOf(raw.trim) ?? fallback.trim,
    screen: oneOf(raw.screen, SCREEN_PRESETS) ?? hexOf(raw.screen) ?? fallback.screen,
    finish: oneOf(raw.finish, FINISHES) ?? fallback.finish,
    antenna: oneOf(raw.antenna, ANTENNAS) ?? fallback.antenna,
    accessory: typeof raw.accessory === "boolean" ? raw.accessory : fallback.accessory,
    eyes: oneOf(raw.eyes, EYE_KINDS) ?? fallback.eyes,
    speed:
      typeof raw.speed === "number" && Number.isFinite(raw.speed)
        ? Math.min(SPEED.max, Math.max(SPEED.min, raw.speed))
        : fallback.speed,
  }
}

export function isDefault(appearance: Appearance, advisorId: AdvisorId): boolean {
  return serializeAppearance(appearance) === serializeAppearance(defaultAppearance(advisorId))
}

function oneOf<T extends string>(value: unknown, options: readonly T[]): T | null {
  return typeof value === "string" && (options as readonly string[]).includes(value) ? (value as T) : null
}

const HEX = /^#[0-9a-f]{6}$/i

export function isHex(value: unknown): value is Hex {
  return typeof value === "string" && HEX.test(value)
}

function hexOf(value: unknown): Hex | null {
  return isHex(value) ? value.toUpperCase() : null
}

function channels(hex: Hex): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number]
}

/** Mixes `a` toward `b` by `t` (0 keeps `a`, 1 gives `b`), per sRGB channel. */
export function mix(a: Hex, b: Hex, t: number): Hex {
  const from = channels(a)
  const to = channels(b)
  const out = from.map((v, i) =>
    Math.round(v + (to[i] - v) * t)
      .toString(16)
      .padStart(2, "0"),
  )
  return `#${out.join("")}`.toUpperCase()
}

/** Perceived brightness from 0 (black) to 1 (white), Rec. 601 weights. */
export function luminance(hex: Hex): number {
  const [r, g, b] = channels(hex)
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255
}

/** The eye colours: mint on dark shells, else the shell mixed toward white, unless a preset or hex is chosen. */
export function glowColors(appearance: Pick<Appearance, "screen" | "shell">): { eye: Hex; halo: Hex } {
  const { screen, shell } = appearance
  const preset = oneOf(screen, SCREEN_PRESETS)
  if (!preset) return { eye: screen, halo: screen }
  const { eye, halo } = SCREENS[preset]
  if (eye && halo) return { eye, halo }
  const tinted =
    luminance(shell) < TONE.darkShell ? TONE.mint : mix(shell, "#FFFFFF", TONE.glowTowardWhite)
  return { eye: tinted, halo: tinted }
}

/** The light and dark stops of the trim gradient, and the stem colour for antennas. */
export function trimColors(trim: Appearance["trim"]): { light: Hex; dark: Hex; stem: Hex } {
  const preset = oneOf(trim, TRIM_PRESETS)
  const pair = preset
    ? TRIMS[preset]
    : {
        light: mix(trim, "#FFFFFF", TONE.customTrimLight),
        dark: mix(trim, "#000000", TONE.customTrimDark),
      }
  return { light: pair.light, dark: pair.dark, stem: mix(pair.light, pair.dark, TONE.trimStem) }
}
