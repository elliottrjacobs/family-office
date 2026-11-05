// Head silhouettes in a 100 by 100 viewBox. The thirteen advisor shapes are ported from
// the cast generator (D01-r03); the nine generic shapes follow the same proportions.
// A shape owns its head, screen, eye positions, ears and molded details; eyes, antennas,
// trim, screen glow and accessories are layered on by the renderer, so any shape takes
// any option.

import type { EyeKind, Shape } from "@/avatars/appearance"

export type Point = readonly [number, number]
export type Box = { x: number; y: number; w: number; h: number }
export type RoundRect = Box & { kind: "rect"; r: number }
export type Circle = { kind: "circle"; cx: number; cy: number; r: number }
export type Head = RoundRect | Circle | { kind: "path"; d: string; bounds: Box }
export type Screen = RoundRect | Circle
export type Ear = RoundRect | Circle
/** A molded groove (dark stroke) or a trim-coloured bolt. */
export type Detail = { kind: "groove"; d: string } | (Circle & { trim: true })

export type ShapeDef = {
  head: Head
  screen: Screen
  eyes: readonly Point[]
  eyeKind: EyeKind
  /** Where an antenna stem meets the top of the head. */
  mount: Point
  ears: readonly Ear[]
  details: readonly Detail[]
}

const rect = (x: number, y: number, w: number, h: number, r: number): RoundRect => ({
  kind: "rect",
  x,
  y,
  w,
  h,
  r,
})
const circle = (cx: number, cy: number, r: number): Circle => ({ kind: "circle", cx, cy, r })
const path = (d: string, x: number, y: number, w: number, h: number): Head => ({
  kind: "path",
  d,
  bounds: { x, y, w, h },
})

/** A closed polygon with each corner rounded by a quadratic curve of radius `r`. */
export function roundedPolygon(points: readonly Point[], r: number): string {
  const n = points.length
  const toward = (from: Point, to: Point): Point => {
    const dx = to[0] - from[0]
    const dy = to[1] - from[1]
    const t = Math.min(r / Math.hypot(dx, dy), 0.5)
    return [round(from[0] + dx * t), round(from[1] + dy * t)]
  }
  const parts = points.map((corner, i) => {
    const before = toward(corner, points[(i + n - 1) % n])
    const after = toward(corner, points[(i + 1) % n])
    return `${i === 0 ? "M" : "L"}${before[0]} ${before[1]}Q${corner[0]} ${corner[1]} ${after[0]} ${after[1]}`
  })
  return `${parts.join("")}Z`
}

const round = (value: number) => Math.round(value * 100) / 100

const HEXAGON: readonly Point[] = [
  [30, 24],
  [70, 24],
  [89, 55],
  [70, 86],
  [30, 86],
  [11, 55],
]
const HOUSE: readonly Point[] = [
  [50, 18],
  [85, 46],
  [85, 88],
  [15, 88],
  [15, 46],
]

export const SHAPES: Record<Shape, ShapeDef> = {
  // The cast, ported from the generator.
  cio: {
    head: rect(16, 28, 68, 58, 20),
    screen: rect(24, 38, 52, 37, 11),
    eyes: [
      [39, 55],
      [61, 55],
    ],
    eyeKind: "pill",
    mount: [50, 28],
    ears: [circle(13, 57, 6.5), circle(87, 57, 6.5)],
    details: [],
  },
  cfo: {
    head: rect(9, 34, 82, 50, 18),
    screen: rect(19, 43, 62, 32, 10),
    eyes: [
      [40, 57],
      [60, 57],
    ],
    eyeKind: "square",
    mount: [50, 34],
    // The right ear is designed here; the cast shows the crank there, which the CFO
    // accessory draws in its place.
    ears: [rect(3, 51, 8, 15, 4), rect(89, 51, 8, 15, 4)],
    details: [],
  },
  planner: {
    head: rect(24, 19, 52, 71, 26),
    screen: rect(31, 34, 38, 42, 15),
    eyes: [
      [42, 53],
      [58, 53],
    ],
    eyeKind: "pill",
    mount: [50, 19],
    ears: [rect(18, 50, 7, 15, 3.5), rect(75, 50, 7, 15, 3.5)],
    details: [],
  },
  tax: {
    head: rect(17, 28, 66, 58, 13),
    screen: rect(25, 41, 50, 33, 9),
    eyes: [
      [40, 58],
      [60, 58],
    ],
    eyeKind: "pill",
    mount: [50, 28],
    ears: [rect(11, 50, 7, 17, 3), rect(82, 50, 7, 17, 3)],
    details: [],
  },
  research: {
    head: circle(50, 57, 33),
    screen: circle(50, 55, 15.5),
    eyes: [[50, 53]],
    eyeKind: "ring",
    mount: [50, 24],
    ears: [circle(16, 58, 5.5), circle(84, 58, 5.5)],
    details: [],
  },
  diligence: {
    head: rect(15, 30, 70, 56, 16),
    screen: rect(23, 43, 54, 31, 9),
    eyes: [
      [39, 58],
      [61, 58],
    ],
    eyeKind: "square",
    mount: [50, 30],
    ears: [rect(9, 50, 7, 17, 3.5), rect(84, 50, 7, 17, 3.5)],
    details: [],
  },
  scout: {
    head: rect(22, 24, 56, 64, 20),
    screen: rect(27, 38, 46, 28, 12),
    eyes: [
      [39.5, 52],
      [60.5, 52],
    ],
    // The cast's binocular "lens" eye is a dot pupil inside the Scout accessory's lens rims.
    eyeKind: "dot",
    mount: [50, 24],
    ears: [],
    details: [{ kind: "groove", d: "M30 76h40" }],
  },
  macro: {
    head: circle(50, 56, 31),
    screen: rect(30, 43, 40, 26, 12),
    eyes: [
      [41, 55],
      [59, 55],
    ],
    eyeKind: "dot",
    mount: [50, 25],
    ears: [],
    details: [],
  },
  options: {
    head: path(
      "M44 23.5a12 12 0 0 1 12 0l21 12.1a12 12 0 0 1 6 10.4v20a12 12 0 0 1-6 10.4l-21 12.1a12 12 0 0 1-12 0L23 76.4A12 12 0 0 1 17 66V46a12 12 0 0 1 6-10.4z",
      17,
      22,
      66,
      68,
    ),
    screen: rect(27, 41, 46, 31, 10),
    eyes: [
      [39, 56],
      [61, 56],
    ],
    eyeKind: "pill",
    mount: [50, 23],
    ears: [],
    details: [],
  },
  technicals: {
    head: rect(10, 33, 80, 52, 18),
    screen: rect(19, 42, 62, 34, 10),
    eyes: [
      [40, 54],
      [60, 54],
    ],
    eyeKind: "pill",
    mount: [50, 33],
    ears: [rect(3, 49, 9, 19, 4.5), rect(88, 49, 9, 19, 4.5)],
    details: [],
  },
  risk: {
    head: path(
      "M18 62C18 38 32 24 50 24S82 38 82 62V78A8 8 0 0 1 74 86H26A8 8 0 0 1 18 78Z",
      18,
      24,
      64,
      62,
    ),
    screen: rect(23, 48, 54, 17, 8.5),
    eyes: [
      [40, 56.5],
      [60, 56.5],
    ],
    eyeKind: "bar",
    mount: [50, 24],
    ears: [],
    details: [
      { kind: "circle", cx: 26, cy: 76, r: 2.4, trim: true },
      { kind: "circle", cx: 74, cy: 76, r: 2.4, trim: true },
      { kind: "groove", d: "M36 76h28" },
    ],
  },
  realestate: {
    head: path(
      "M45.5 22.3a7 7 0 0 1 9 0l24 20.4A8 8 0 0 1 81.5 49v32a7 7 0 0 1-7 7h-49a7 7 0 0 1-7-7V49a8 8 0 0 1 3-6.3z",
      18.5,
      20.7,
      63,
      67.3,
    ),
    screen: rect(28, 50, 44, 28, 9),
    eyes: [
      [40.5, 63],
      [59.5, 63],
    ],
    eyeKind: "pill",
    mount: [50, 21],
    ears: [],
    details: [],
  },
  ventures: {
    head: path("M50 12C67 25 77 44 77 64V78A8 8 0 0 1 69 86H31A8 8 0 0 1 23 78V64C23 44 33 25 50 12Z", 23, 12, 54, 74),
    screen: circle(50, 61, 14.5),
    eyes: [
      [44, 59],
      [56, 59],
    ],
    eyeKind: "dot",
    mount: [50, 12],
    ears: [],
    details: [],
  },

  // Generic shapes, designed to sit beside the cast.
  rounded: {
    head: rect(15, 27, 70, 60, 24),
    screen: rect(24, 39, 52, 37, 12),
    eyes: [
      [39, 57.5],
      [61, 57.5],
    ],
    eyeKind: "pill",
    mount: [50, 27],
    ears: [circle(12, 57, 6), circle(88, 57, 6)],
    details: [],
  },
  square: {
    head: rect(17, 24, 66, 64, 9),
    screen: rect(25, 36, 50, 40, 6),
    eyes: [
      [40, 56],
      [60, 56],
    ],
    eyeKind: "square",
    mount: [50, 24],
    ears: [rect(11, 47, 7, 18, 2.5), rect(82, 47, 7, 18, 2.5)],
    details: [],
  },
  capsule: {
    head: rect(25, 14, 50, 76, 25),
    screen: rect(31, 32, 38, 40, 14),
    eyes: [
      [42, 52],
      [58, 52],
    ],
    eyeKind: "pill",
    mount: [50, 14],
    ears: [rect(19, 46, 7, 14, 3.5), rect(74, 46, 7, 14, 3.5)],
    details: [{ kind: "groove", d: "M41 81h18" }],
  },
  circle: {
    head: circle(50, 56, 32),
    screen: rect(31, 42, 38, 28, 12),
    eyes: [
      [41, 56],
      [59, 56],
    ],
    eyeKind: "dot",
    mount: [50, 24],
    ears: [circle(15, 56, 5.5), circle(85, 56, 5.5)],
    details: [],
  },
  hexagon: {
    head: path(roundedPolygon(HEXAGON, 7), 11, 24, 78, 62),
    screen: rect(27, 40, 46, 30, 9),
    eyes: [
      [40, 55],
      [60, 55],
    ],
    eyeKind: "pill",
    mount: [50, 24],
    ears: [],
    details: [{ kind: "groove", d: "M40 78h20" }],
  },
  dome: {
    head: path("M14 64A36 36 0 0 1 86 64V80A8 8 0 0 1 78 88H22A8 8 0 0 1 14 80Z", 14, 28, 72, 60),
    screen: rect(24, 50, 52, 27, 10),
    eyes: [
      [40, 63.5],
      [60, 63.5],
    ],
    eyeKind: "pill",
    mount: [50, 28],
    ears: [circle(10.5, 70, 5), circle(89.5, 70, 5)],
    details: [],
  },
  wide: {
    head: rect(6, 36, 88, 46, 16),
    screen: rect(16, 44, 68, 30, 10),
    eyes: [
      [38, 59],
      [62, 59],
    ],
    eyeKind: "square",
    mount: [50, 36],
    ears: [],
    details: [],
  },
  house: {
    head: path(roundedPolygon(HOUSE, 6), 15, 20, 70, 68),
    screen: rect(27, 51, 46, 29, 9),
    eyes: [
      [40.5, 65.5],
      [59.5, 65.5],
    ],
    eyeKind: "pill",
    mount: [50, 20],
    ears: [],
    details: [],
  },
  rocket: {
    head: path("M50 10C64 18 76 34 78 54V80A8 8 0 0 1 70 88H30A8 8 0 0 1 22 80V54C24 34 36 18 50 10Z", 22, 10, 56, 78),
    screen: rect(31, 50, 38, 26, 11),
    eyes: [
      [42, 63],
      [58, 63],
    ],
    eyeKind: "dot",
    mount: [50, 10],
    ears: [],
    details: [{ kind: "groove", d: "M30 40h40" }],
  },
}

/** The bounding box of a head, screen or ear. */
export function boxOf(shape: Head | Screen | Ear): Box {
  if (shape.kind === "circle") return { x: shape.cx - shape.r, y: shape.cy - shape.r, w: shape.r * 2, h: shape.r * 2 }
  if (shape.kind === "path") return shape.bounds
  return { x: shape.x, y: shape.y, w: shape.w, h: shape.h }
}
