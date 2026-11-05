// SVG fragments for the robot: ears and trim, antennas, the role accessory of each
// advisor, eyes in every state pose, and state extras on the screen. Geometry is in the
// 100 by 100 viewBox of shapes.ts; accessories are drawn in their home silhouette's
// coordinates and mapped onto whichever shape is chosen.

import type { ReactNode, SVGAttributes } from "react"

import type { AdvisorId, Antenna, EyeKind, Hex, RobotState } from "@/avatars/appearance"
import { boxOf, SHAPES, type Box, type Ear, type Head, type Point, type Screen, type ShapeDef } from "@/avatars/shapes"

/** Resolved colours and scoped ids for one robot instance. */
export type Paint = {
  shell: Hex
  eye: Hex
  halo: Hex
  trim: { light: Hex; dark: Hex; stem: Hex }
  /** Scoped `url(#…)` references. */
  url: { trim: string; gold: string; glowBlur: string | null }
  /** At small sizes: no filters and no sheen. */
  compact: boolean
}

/** Fixed part colours from the cast. */
export const PART = {
  dark: "#3A3F49",
  lensDark: "#101216",
  slot: "#2A2E36",
  coinStroke: "#B8862A",
  coinRing: "#F3D78A",
  crankKnob: "#4A4F5A",
  compassFace: "#FFFFFF",
  compassRing: "#AEB6C2",
  compassNorth: "#E5484D",
  compassSouth: "#6B717C",
  pennant: "#F5C343",
  periscopeLens: "#9BE8FF",
  twinLeft: "#F0ABFC",
  twinRight: "#5EEAD4",
  macroBall: "#FFD27A",
  eyeshade: "#073B26",
  eyeshadeEdge: "#B9F5D3",
  pencil: "#F5C343",
  eraser: "#F28C9B",
  pencilTip: "#E9D3A8",
  glasses: "#E6EAF0",
  check: "#1F9D63",
  chimney: "#7A4326",
  window: "#FFE7A8",
  noseLight: "#FFD27A",
  error: "#FF5A5F",
  gold: { light: "#FBE6A6", dark: "#D9A63A" },
  screen: { top: "#262A33", bottom: "#0B0C10" },
} as const

type SvgProps = SVGAttributes<SVGElement>

/** Renders a head, screen or ear geometry as its SVG element. */
export function Geometry({ shape, ...props }: { shape: Head | Screen | Ear } & SvgProps) {
  if (shape.kind === "circle") return <circle cx={shape.cx} cy={shape.cy} r={shape.r} {...props} />
  if (shape.kind === "path") return <path d={shape.d} {...props} />
  return <rect x={shape.x} y={shape.y} width={shape.w} height={shape.h} rx={shape.r} {...props} />
}

// Anchoring: how an accessory drawn for its home silhouette lands on another shape.

type Anchor = "head" | "mount" | "screenTop" | "headRight"

function anchorPoint(def: ShapeDef, anchor: Exclude<Anchor, "head">): Point {
  if (anchor === "mount") return def.mount
  if (anchor === "screenTop") {
    const box = boxOf(def.screen)
    return [box.x + box.w / 2, box.y]
  }
  const box = boxOf(def.head)
  return [box.x + box.w, box.y + box.h / 2]
}

function transformFor(anchor: Anchor, home: ShapeDef, def: ShapeDef): string | undefined {
  if (home === def) return undefined
  if (anchor === "head") {
    const from: Box = boxOf(home.head)
    const to: Box = boxOf(def.head)
    const sx = to.w / from.w
    const sy = to.h / from.h
    return `matrix(${sx} 0 0 ${sy} ${to.x - from.x * sx} ${to.y - from.y * sy})`
  }
  const [fx, fy] = anchorPoint(home, anchor)
  const [tx, ty] = anchorPoint(def, anchor)
  return tx === fx && ty === fy ? undefined : `translate(${tx - fx} ${ty - fy})`
}

function Anchored({ anchor, home, def, children }: { anchor: Anchor; home: ShapeDef; def: ShapeDef; children: ReactNode }) {
  return <g transform={transformFor(anchor, home, def)}>{children}</g>
}

// Ears, trim and molded details.

export function Ears({ def, paint, hide = [] }: { def: ShapeDef; paint: Paint; hide?: readonly number[] }) {
  return (
    <g data-part="ears">
      {def.ears.map((ear, i) => (hide.includes(i) ? null : <Geometry key={i} shape={ear} fill={paint.url.trim} />))}
    </g>
  )
}

export function Details({ def, paint }: { def: ShapeDef; paint: Paint }) {
  return (
    <g data-part="details">
      {def.details.map((detail, i) =>
        detail.kind === "groove" ? (
          <path key={i} d={detail.d} stroke="#000" strokeOpacity={0.15} strokeWidth={2} strokeLinecap="round" />
        ) : (
          <circle key={i} cx={detail.cx} cy={detail.cy} r={detail.r} fill={paint.url.trim} />
        ),
      )}
    </g>
  )
}

// Antennas, drawn behind the head from the mount point upward.

type AntennaDef = { height: number; draw: (x: number, y: number, paint: Paint, ball: Hex | null) => ReactNode }

export const ANTENNA_PARTS: Record<Exclude<Antenna, "none">, AntennaDef> = {
  compass: {
    height: 22,
    draw: (x, y, paint) => (
      <>
        <path d={`M${x} ${y}V${y - 9}`} stroke={paint.trim.stem} strokeWidth={3} strokeLinecap="round" />
        <circle cx={x} cy={y - 15} r={7} fill={PART.compassFace} stroke={PART.compassRing} strokeWidth={1.6} />
        <path d={`M${x} ${y - 20.5}l2.2 5.5h-4.4z`} fill={PART.compassNorth} />
        <path d={`M${x} ${y - 9.5}l2.2-5.5h-4.4z`} fill={PART.compassSouth} />
      </>
    ),
  },
  ball: {
    height: 15,
    draw: (x, y, paint, ball) => (
      <>
        <path d={`M${x} ${y}V${y - 9}`} stroke={paint.trim.stem} strokeWidth={2.6} strokeLinecap="round" />
        <circle cx={x} cy={y - 11} r={ball ? 4 : 3.8} fill={ball ?? paint.url.trim} />
      </>
    ),
  },
  flag: {
    height: 16.5,
    draw: (x, y, paint) => (
      <>
        <path d={`M${x} ${y}V${y - 15}`} stroke={paint.trim.stem} strokeWidth={2.6} strokeLinecap="round" />
        <path d={`M${x + 1} ${y - 15}h12l-3.5 4.5 3.5 4.5H${x + 1}z`} fill={PART.pennant} />
        <path d={`M${x + 1} ${y - 12.6}h9.8`} stroke="#fff" strokeWidth={1.4} opacity={0.8} />
      </>
    ),
  },
  periscope: {
    height: 19.5,
    draw: (x, y, paint) => (
      <>
        <path
          d={`M${x} ${y}V${y - 15}H${x + 11}`}
          fill="none"
          stroke={paint.trim.stem}
          strokeWidth={5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <rect x={x + 10} y={y - 19.5} width={8} height={9} rx={2.5} fill={PART.dark} />
        <circle cx={x + 17} cy={y - 15} r={2.4} fill={PART.periscopeLens} />
      </>
    ),
  },
  twin: {
    height: 16,
    draw: (x, y, paint) => (
      <>
        <path
          d={`M${x - 10} ${y + 4}L${x - 17} ${y - 10}M${x + 10} ${y + 4}L${x + 17} ${y - 10}`}
          stroke={paint.trim.stem}
          strokeWidth={2.6}
          strokeLinecap="round"
        />
        <circle cx={x - 17} cy={y - 12} r={3.8} fill={PART.twinLeft} />
        <circle cx={x + 17} cy={y - 12} r={3.8} fill={PART.twinRight} />
      </>
    ),
  },
}

/** Advisors whose ball antenna has its own colour in the cast. */
const BALL_COLORS: Partial<Record<AdvisorId, Hex>> = { macro: PART.macroBall }

const ANTENNA_CLEARANCE = 1

export function AntennaPart({ kind, def, paint, advisor }: { kind: Antenna; def: ShapeDef; paint: Paint; advisor: AdvisorId }) {
  if (kind === "none") return null
  const part = ANTENNA_PARTS[kind]
  const [x, mountY] = def.mount
  // A tall antenna on a tall head slides down behind the head rather than leave the viewBox.
  const y = Math.max(mountY, part.height + ANTENNA_CLEARANCE)
  return <g data-part="antenna">{part.draw(x, y, paint, BALL_COLORS[advisor] ?? null)}</g>
}

// Role accessories.

type Layer = (def: ShapeDef, paint: Paint) => ReactNode

export type AccessoryDef = {
  /** Behind the head, after the ears. */
  back?: Layer
  /** On the head, before the screen. */
  face?: Layer
  /** Around the screen, beneath it. */
  rim?: Layer
  /** On the screen, beneath the eyes. */
  lens?: Layer
  /** Over everything else. */
  over?: Layer
  /** Ear indices the accessory replaces. */
  hideEars?: readonly number[]
  /** A second eye colour (two-tone eyes). */
  secondEye?: Hex
  /** A small chart on the screen when idle or done. */
  chart?: boolean
}

/** A trim rim around the screen, then a dark gasket, sized from the screen itself. */
function screenRim(screen: Screen, outer: number, inner: number, paint: Paint) {
  const grow = (by: number): Screen =>
    screen.kind === "circle"
      ? { ...screen, r: screen.r + by }
      : { ...screen, x: screen.x - by, y: screen.y - by, w: screen.w + by * 2, h: screen.h + by * 2, r: screen.r + by }
  return (
    <>
      <Geometry shape={grow(outer)} fill={paint.url.trim} />
      <Geometry shape={grow(inner)} fill={PART.dark} />
    </>
  )
}

const home = (id: AdvisorId) => SHAPES[id]

export const ACCESSORIES: Record<AdvisorId, AccessoryDef> = {
  // The CIO's compass, the Planner's pennant and the Scout's periscope are antennas.
  cio: {},
  cfo: {
    hideEars: [1],
    back: (def, paint) => (
      <Anchored anchor="headRight" home={home("cfo")} def={def}>
        <path
          d="M90 60h6V47"
          fill="none"
          stroke={paint.trim.stem}
          strokeWidth={3}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx={96} cy={45} r={3.8} fill={PART.crankKnob} />
      </Anchored>
    ),
    face: (def, paint) => (
      <Anchored anchor="mount" home={home("cfo")} def={def}>
        <circle cx={50} cy={28} r={8} fill={paint.url.gold} stroke={PART.coinStroke} />
        <circle cx={50} cy={28} r={5} fill="none" stroke={PART.coinRing} />
        <rect x={37} y={31} width={26} height={5.5} rx={2.75} fill={PART.slot} />
      </Anchored>
    ),
  },
  planner: {},
  tax: {
    over: (def) => (
      <Anchored anchor="head" home={home("tax")} def={def}>
        <path d="M15 42Q50 22 85 42L80 47Q50 31 20 47Z" fill={PART.eyeshade} opacity={0.62} />
        <path d="M15.5 42Q50 22 84.5 42" fill="none" stroke={PART.eyeshadeEdge} strokeOpacity={0.7} strokeWidth={1.3} />
        <g transform="rotate(-24 86 40)">
          <rect x={83.5} y={22} width={5} height={22} rx={1.2} fill={PART.pencil} />
          <rect x={83.5} y={22} width={5} height={4} fill={PART.eraser} />
          <path d="M83.5 44l2.5 5 2.5-5z" fill={PART.pencilTip} />
        </g>
      </Anchored>
    ),
  },
  research: {
    rim: (def, paint) => screenRim(def.screen, 4, 1.7, paint),
  },
  diligence: {
    face: (def) => (
      <Anchored anchor="screenTop" home={home("diligence")} def={def}>
        <circle cx={50} cy={36.5} r={4.2} fill="#fff" />
        <path
          d="M47.8 36.6l1.6 1.6 3-3.2"
          fill="none"
          stroke={PART.check}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </Anchored>
    ),
    over: (def) => {
      const lens = { w: 17, h: 14, r: 4 }
      const [first, second] = def.eyes
      return (
        <g fill="none" stroke={PART.glasses} strokeWidth={2.4}>
          {def.eyes.map(([x, y], i) => (
            <rect key={i} x={x - lens.w / 2} y={y - lens.h / 2} width={lens.w} height={lens.h} rx={lens.r} />
          ))}
          {second ? (
            <path d={`M${first[0] + lens.w / 2} ${first[1] - 1}H${second[0] - lens.w / 2}`} />
          ) : null}
        </g>
      )
    },
  },
  scout: {
    lens: (def, paint) => (
      <g>
        {def.eyes.map(([x, y], i) => (
          <g key={i}>
            <circle cx={x} cy={y} r={9} fill={paint.url.trim} />
            <circle cx={x} cy={y} r={7} fill={PART.lensDark} />
          </g>
        ))}
      </g>
    ),
  },
  macro: {
    back: (def, paint) => (
      <Anchored anchor="head" home={home("macro")} def={def}>
        <g transform="rotate(-12 50 70)">
          <path d="M6 70A44 9.5 0 0 1 94 70" fill="none" stroke={paint.trim.stem} strokeWidth={3.2} opacity={0.75} />
        </g>
      </Anchored>
    ),
    over: (def, paint) => (
      <Anchored anchor="head" home={home("macro")} def={def}>
        <g transform="rotate(-12 50 70)">
          <path d="M6 70A44 9.5 0 0 0 94 70" fill="none" stroke={paint.trim.stem} strokeWidth={3.6} />
        </g>
      </Anchored>
    ),
  },
  options: { secondEye: PART.twinRight },
  technicals: {
    hideEars: [0, 1],
    chart: true,
    back: (def) =>
      def.ears.length ? (
        <g>
          {def.ears.map((ear, i) => (
            <Geometry key={i} shape={ear} fill={PART.dark} />
          ))}
        </g>
      ) : (
        <Anchored anchor="head" home={home("technicals")} def={def}>
          {home("technicals").ears.map((ear, i) => (
            <Geometry key={i} shape={ear} fill={PART.dark} />
          ))}
        </Anchored>
      ),
    face: (def, paint) => (
      <Anchored anchor="head" home={home("technicals")} def={def}>
        <path d="M7.5 52C7.5 18 92.5 18 92.5 52" fill="none" stroke={paint.trim.stem} strokeWidth={3.4} strokeLinecap="round" />
      </Anchored>
    ),
    over: (def, paint) => (
      <Anchored anchor="head" home={home("technicals")} def={def}>
        <path d="M7.5 66q2 15 20 16" fill="none" stroke={paint.trim.stem} strokeWidth={2} strokeLinecap="round" />
        <circle cx={28} cy={82} r={3} fill={PART.dark} />
      </Anchored>
    ),
  },
  risk: {
    over: (def, paint) => (
      <Anchored anchor="mount" home={home("risk")} def={def}>
        <rect x={45.5} y={15} width={9} height={16} rx={4.5} fill="#000" fillOpacity={0.22} />
        <rect x={46.5} y={15} width={7} height={15} rx={3.5} fill={paint.url.trim} />
      </Anchored>
    ),
  },
  realestate: {
    back: (def) => (
      <Anchored anchor="head" home={home("realestate")} def={def}>
        <rect x={64} y={24} width={8} height={15} rx={2} fill={PART.chimney} />
      </Anchored>
    ),
    face: (def) => (
      <Anchored anchor="head" home={home("realestate")} def={def}>
        <rect x={44} y={34} width={12} height={9} rx={2} fill={PART.window} opacity={0.9} />
        <path d="M50 34v9M44 38.5h12" stroke="#000" strokeOpacity={0.2} />
      </Anchored>
    ),
  },
  ventures: {
    rim: (def, paint) => screenRim(def.screen, 3.5, 1.3, paint),
    face: (def) => (
      <>
        <Anchored anchor="head" home={home("ventures")} def={def}>
          <path d="M23 64L10 84L24 79Z" fill="#000" fillOpacity={0.18} />
          <path d="M77 64L90 84L76 79Z" fill="#000" fillOpacity={0.18} />
        </Anchored>
        <Anchored anchor="mount" home={home("ventures")} def={def}>
          <circle cx={50} cy={20} r={2.6} fill={PART.noseLight} />
        </Anchored>
      </>
    ),
  },
}

// Eyes. Each kind has a pose per state, ported from the cast generator; `error` is new.

/** Pose constants per eye kind; half extents are used to fit eyes on small screens. */
export const EYE = {
  pill: { w: 5.6, h: { idle: 10.5, thinking: 7, writing: 6, speaking: 8.5 }, read: [9, 3.6], half: [2.8, 5.25] },
  dot: { r: 3.7, read: [8, 3.2], half: [3.7, 3.7] },
  square: { size: 7.2, rx: 1.8, read: [9, 3.6], half: [3.6, 3.6] },
  bar: { w: 11, h: 4.2, read: [14, 2.6], half: [5.5, 2.1] },
  ring: { r: 7.5, stroke: 2.6, pupil: 3.2, read: [7, 3], readStroke: 2.4, half: [8.8, 8.8] },
  offset: { thinking: [2.6, -3.5], reading: [0, 2], writing: [0, 2], speaking: [0, -2] },
  done: { ring: 14, other: 9, stroke: 2.6 },
  sleeping: { ring: 13, other: 8, thickness: 2.4 },
  error: { ring: 5, other: 3.2, stroke: 2.4 },
  margin: { between: 1, screen: 1.5 },
  compactHalo: { pad: 1.8, opacity: 0.35 },
} as const

export const SLEEPING_EYE_OPACITY = 0.5

type Pose = { kind: EyeKind; state: RobotState; x: number; y: number; color: Hex }

function pill(x: number, y: number, w: number, h: number, color: Hex) {
  return <rect x={x - w / 2} y={y - h / 2} width={w} height={h} rx={Math.min(w, h) / 2} fill={color} />
}

function offsetFor(state: RobotState): readonly [number, number] {
  return state in EYE.offset ? EYE.offset[state as keyof typeof EYE.offset] : [0, 0]
}

export function EyePose({ kind, state, x, y, color }: Pose) {
  const ring = kind === "ring"
  if (state === "done") {
    const w = ring ? EYE.done.ring : EYE.done.other
    return (
      <path
        d={`M${x - w / 2} ${y + 1}q${w / 2} ${-w * 0.7} ${w} 0`}
        fill="none"
        stroke={color}
        strokeWidth={EYE.done.stroke}
        strokeLinecap="round"
      />
    )
  }
  if (state === "sleeping") return pill(x, y + 1, ring ? EYE.sleeping.ring : EYE.sleeping.other, EYE.sleeping.thickness, color)
  if (state === "error") {
    const s = ring ? EYE.error.ring : EYE.error.other
    return (
      <path
        d={`M${x - s} ${y - s}L${x + s} ${y + s}M${x + s} ${y - s}L${x - s} ${y + s}`}
        stroke={color}
        strokeWidth={EYE.error.stroke}
        strokeLinecap="round"
      />
    )
  }
  const reading = state === "reading"
  const [dx, dy] = offsetFor(state)
  switch (kind) {
    case "square": {
      const { size, rx, read } = EYE.square
      return reading ? (
        pill(x, y + 1, read[0], read[1], color)
      ) : (
        <rect x={x - size / 2 + dx} y={y - size / 2 + dy} width={size} height={size} rx={rx} fill={color} />
      )
    }
    case "dot":
      return reading ? pill(x, y + 1, EYE.dot.read[0], EYE.dot.read[1], color) : <circle cx={x + dx} cy={y + dy} r={EYE.dot.r} fill={color} />
    case "bar":
      return reading ? pill(x, y, EYE.bar.read[0], EYE.bar.read[1], color) : pill(x + dx, y + dy * 0.5, EYE.bar.w, EYE.bar.h, color)
    case "ring":
      return reading ? (
        <ellipse
          cx={x}
          cy={y + 1}
          rx={EYE.ring.read[0]}
          ry={EYE.ring.read[1]}
          fill="none"
          stroke={color}
          strokeWidth={EYE.ring.readStroke}
        />
      ) : (
        <>
          <circle cx={x} cy={y} r={EYE.ring.r} fill="none" stroke={color} strokeWidth={EYE.ring.stroke} />
          <circle cx={x + dx * 0.8} cy={y + dy * 0.7} r={EYE.ring.pupil} fill={color} />
        </>
      )
    default: {
      if (reading) return pill(x, y - 1, EYE.pill.read[0], EYE.pill.read[1], color)
      const height = state in EYE.pill.h ? EYE.pill.h[state as keyof typeof EYE.pill.h] : EYE.pill.h.idle
      return pill(x + dx, y + dy, EYE.pill.w, height, color)
    }
  }
}

/** Scale that keeps the chosen eye kind inside the screen and apart from its twin. */
export function eyeFit(def: ShapeDef, kind: EyeKind): number {
  const [halfW, halfH] = EYE[kind].half
  const screen = boxOf(def.screen)
  let fit = (screen.h / 2 - EYE.margin.screen) / halfH
  if (def.eyes.length > 1) {
    const gap = Math.abs(def.eyes[1][0] - def.eyes[0][0])
    fit = Math.min(fit, (gap / 2 - EYE.margin.between) / halfW)
  }
  return Math.min(1, fit)
}

function scaled(x: number, y: number, s: number) {
  return s === 1 ? undefined : `translate(${x} ${y}) scale(${s}) translate(${-x} ${-y})`
}

export function Eyes({
  def,
  kind,
  state,
  paint,
  secondEye,
}: {
  def: ShapeDef
  kind: EyeKind
  state: RobotState
  paint: Paint
  secondEye?: Hex
}) {
  const fit = eyeFit(def, kind)
  const colorOf = (i: number, base: Hex) => (state === "error" ? PART.error : secondEye && i === 1 ? secondEye : base)
  const draw = (base: Hex) =>
    def.eyes.map(([x, y], i) => (
      <g key={i} transform={scaled(x, y, fit)}>
        <EyePose kind={kind} state={state} x={x} y={y} color={colorOf(i, base)} />
      </g>
    ))
  const [halfW, halfH] = EYE[kind].half
  return (
    <g data-part="eyes" opacity={state === "sleeping" ? SLEEPING_EYE_OPACITY : 1}>
      {paint.url.glowBlur ? (
        <g data-layer="glow" filter={paint.url.glowBlur} opacity={0.85}>
          {draw(paint.halo)}
        </g>
      ) : (
        <g data-layer="glow" opacity={EYE.compactHalo.opacity}>
          {def.eyes.map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r={(Math.max(halfW, halfH) + EYE.compactHalo.pad) * fit} fill={colorOf(i, paint.halo)} />
          ))}
        </g>
      )}
      {draw(paint.eye)}
    </g>
  )
}

// State extras along the bottom of the screen.

export const EXTRAS = {
  inset: 6,
  dots: { spacing: 5, r: 1.5, opacities: [0.35, 0.65, 0.95] },
  reading: { margin: 6, h: 1.6, done: 0.45 },
  writing: { margin: 8, h: 2.6, done: 0.62 },
  speaking: { heights: [3, 6, 8.5, 5.5, 3], step: 3.1, w: 2 },
  chart: [
    { dx: -9, h: 5, opacity: 1, lift: 0 },
    { dx: -2, h: 7, opacity: 0.55, lift: 2 },
    { dx: 5, h: 9, opacity: 1, lift: 4 },
  ],
  zigzag: { w: 12, rise: 2 },
} as const

export function Extras({ def, state, paint, chart }: { def: ShapeDef; state: RobotState; paint: Paint; chart: boolean }) {
  const box = boxOf(def.screen)
  const cx = box.x + box.w / 2
  const bottom = box.y + box.h
  const glow = paint.eye
  let content: ReactNode = null
  if (state === "thinking") {
    content = EXTRAS.dots.opacities.map((opacity, i) => (
      <circle
        key={i}
        cx={cx - EXTRAS.dots.spacing + i * EXTRAS.dots.spacing}
        cy={bottom - EXTRAS.inset}
        r={EXTRAS.dots.r}
        fill={glow}
        opacity={opacity}
      />
    ))
  } else if (state === "reading" || state === "writing") {
    const bar = EXTRAS[state]
    const w = box.w - bar.margin * 2
    const y = bottom - 7
    content = (
      <>
        <rect x={box.x + bar.margin} y={y} width={w} height={bar.h} rx={bar.h / 2} fill={glow} opacity={state === "reading" ? 0.45 : 0.2} />
        <rect x={box.x + bar.margin} y={y} width={w * bar.done} height={bar.h} rx={bar.h / 2} fill={glow} />
      </>
    )
  } else if (state === "speaking") {
    const { heights, step, w } = EXTRAS.speaking
    content = heights.map((h, i) => (
      <rect key={i} x={cx - 7 + i * step} y={bottom - 7 - h / 2} width={w} height={h} rx={w / 2} fill={glow} />
    ))
  } else if (state === "error") {
    const { w, rise } = EXTRAS.zigzag
    const steps = Array.from({ length: 6 }, (_, i) => `l${w / 6} ${i % 2 ? rise : -rise}`).join("")
    content = (
      <path
        d={`M${cx - w / 2} ${bottom - EXTRAS.inset}${steps}`}
        fill="none"
        stroke={PART.error}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    )
  } else if (chart && (state === "idle" || state === "done")) {
    content = (
      <g fill={glow}>
        {EXTRAS.chart.map((bar, i) => (
          <rect key={i} x={cx + bar.dx} y={bottom - 10 - bar.lift} width={3} height={bar.h} rx={0.8} opacity={bar.opacity} />
        ))}
      </g>
    )
  }
  return <g data-part="mouth">{content}</g>
}

export const SLEEP_Z = [
  { x: 80, y: 22, size: 11, opacity: 1, darken: 0.1 },
  { x: 88, y: 13, size: 8, opacity: 0.7, darken: 0 },
] as const
