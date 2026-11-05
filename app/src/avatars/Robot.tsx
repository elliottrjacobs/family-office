// One advisor robot as a single SVG with painted lighting (KTD16): contact shadow, ears
// and trim, antenna, a shell with a vertical gradient, a specular highlight and a rim
// light, a recessed screen with glowing eyes, state extras, details and the accessory.

import { type CSSProperties, useId } from "react"

import {
  ADVISORS,
  type AdvisorId,
  type Appearance,
  glowColors,
  mix,
  type RobotState,
  trimColors,
} from "@/avatars/appearance"
import {
  ACCESSORIES,
  AntennaPart,
  Details,
  Ears,
  Extras,
  Eyes,
  Geometry,
  type Paint,
  PART,
  SLEEP_Z,
} from "@/avatars/parts"
import { boxOf, SHAPES } from "@/avatars/shapes"
import { useReducedMotion } from "@/avatars/states"
import { useAppearance } from "@/avatars/store"

import "./animations.css"

/** At or below this pixel size the robot drops blur filters and the screen sheen. */
export const COMPACT_SIZE = 40

/** Lighting constants. */
export const LIGHT = {
  gloss: { top: 0.42, mid: 0.55, base: 0.2 },
  matte: { top: 0.12, base: 0.1 },
  outline: { darken: 0.28, opacity: 0.35, width: 1 },
  specular: { cx: 0.3, cy: 0.2, r: 0.62, stops: [0.5, 0.1, 0] },
  glint: { cx: 36, above: 4, rx: 11, ry: 3.2, rotate: -12, opacity: 0.45 },
  rim: { opacity: 0.8, reach: 0.42, width: 1.5 },
  shadow: { cx: 50, cy: 95, rx: 25, ry: 2.8, opacity: 0.09, soft: { rx: 21, ry: 3.4, opacity: 0.16, blur: 1.4 } },
  screenShade: { opacity: 0.55, reach: 0.35 },
  screenEdge: { inset: 0.6, opacity: 0.08 },
  sheen: { inset: 5, opacity: 0.1, width: 2 },
  glowBlur: 2,
  errorTilt: -6,
  tiltOrigin: [50, 88],
} as const

export type RobotProps = {
  advisor: AdvisorId
  /** Rendered width and height in pixels. */
  size?: number
  /** A look to show instead of the advisor's stored one (used by the customize preview). */
  appearance?: Appearance
  state?: RobotState
  /** Whether the robot animates. Static robots, and every robot under reduced motion, show the pose only. */
  live?: boolean
  /** Animation speed multiplier, 0 to 2; defaults to the appearance's speed. 0 pauses. */
  speed?: number
  /** Speaking amplitude, 0 to 1, from `useSpeakingLevel`. */
  level?: number
  className?: string
}

/** Lowest rate the CSS divides durations by; speed 0 pauses instead. */
export const MIN_RATE = 0.05

/** Deterministic per-instance timing in [0, 1) from the instance id, so robots blink out of step. */
function seeded(id: string, salt: number): number {
  let hash = 2166136261 ^ salt
  for (let i = 0; i < id.length; i++) {
    hash ^= id.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return ((hash >>> 0) % 10007) / 10007
}

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

export function Robot({
  advisor,
  size = 64,
  appearance,
  state = "idle",
  live = false,
  speed,
  level = 0,
  className,
}: RobotProps) {
  const stored = useAppearance(advisor)
  const reduced = useReducedMotion()
  const look = appearance ?? stored
  const id = `fo-av-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`
  const compact = size <= COMPACT_SIZE
  const def = SHAPES[look.shape]
  const accessory = look.accessory ? ACCESSORIES[advisor] : {}
  const glow = glowColors(look)
  const ref = (name: string) => `${id}-${name}`
  const url = (name: string) => `url(#${ref(name)})`
  const paint: Paint = {
    shell: look.shell,
    eye: glow.eye,
    halo: glow.halo,
    trim: trimColors(look.trim),
    url: { trim: url("trim"), gold: url("gold"), glowBlur: compact ? null : url("glow") },
    compact,
  }
  const gloss = look.finish === "gloss"
  const screenBox = boxOf(def.screen)
  const glintY = screenBox.y - LIGHT.glint.above
  const [tiltX, tiltY] = LIGHT.tiltOrigin
  const rate = clamp(speed ?? look.speed, 0, 2)
  const animated = live && !reduced
  const style = { "--fo-avatar-speed": rate } as Record<string, number | string>
  if (animated) {
    const blink = 3 + seeded(id, 1) * 2
    const lookPeriod = 4 + seeded(id, 2) * 3
    Object.assign(style, {
      "--fo-avatar-rate": Math.max(rate, MIN_RATE),
      "--fo-avatar-level": clamp(Number.isFinite(level) ? level : 0, 0, 1),
      "--fo-blink-period": `${blink.toFixed(2)}s`,
      "--fo-blink-delay": `${(-seeded(id, 3) * blink).toFixed(2)}s`,
      "--fo-look-period": `${lookPeriod.toFixed(2)}s`,
      "--fo-look-delay": `${(-seeded(id, 4) * lookPeriod).toFixed(2)}s`,
    })
  }
  const classes = [
    animated ? `fo-avatar-live fo-avatar-${state}` : null,
    animated && rate === 0 ? "fo-avatar-paused" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ")

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      role="img"
      aria-label={`${ADVISORS[advisor].name} ${state}`}
      className={classes || undefined}
      style={style as CSSProperties}
      data-advisor={advisor}
      data-state={state}
      data-live={animated ? "true" : "false"}
      data-finish={look.finish}
    >
      <defs>
        <linearGradient id={ref("shell")} x1="0" y1="0" x2="0" y2="1">
          {gloss ? (
            <>
              <stop offset="0" stopColor={mix(look.shell, "#FFFFFF", LIGHT.gloss.top)} />
              <stop offset={LIGHT.gloss.mid} stopColor={look.shell} />
              <stop offset="1" stopColor={mix(look.shell, "#000000", LIGHT.gloss.base)} />
            </>
          ) : (
            <>
              <stop offset="0" stopColor={mix(look.shell, "#FFFFFF", LIGHT.matte.top)} />
              <stop offset="1" stopColor={mix(look.shell, "#000000", LIGHT.matte.base)} />
            </>
          )}
        </linearGradient>
        {gloss ? (
          <>
            <radialGradient id={ref("specular")} cx={LIGHT.specular.cx} cy={LIGHT.specular.cy} r={LIGHT.specular.r}>
              {LIGHT.specular.stops.map((opacity, i, all) => (
                <stop key={i} offset={i / (all.length - 1)} stopColor="#FFFFFF" stopOpacity={opacity} />
              ))}
            </radialGradient>
            <linearGradient id={ref("rim")} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#FFFFFF" stopOpacity={LIGHT.rim.opacity} />
              <stop offset={LIGHT.rim.reach} stopColor="#FFFFFF" stopOpacity={0} />
            </linearGradient>
          </>
        ) : null}
        <linearGradient id={ref("screen")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={PART.screen.top} />
          <stop offset="1" stopColor={PART.screen.bottom} />
        </linearGradient>
        <linearGradient id={ref("screen-shade")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#000000" stopOpacity={LIGHT.screenShade.opacity} />
          <stop offset={LIGHT.screenShade.reach} stopColor="#000000" stopOpacity={0} />
        </linearGradient>
        <linearGradient id={ref("trim")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={paint.trim.light} />
          <stop offset="1" stopColor={paint.trim.dark} />
        </linearGradient>
        <radialGradient id={ref("gold")} cx="0.35" cy="0.3">
          <stop offset="0" stopColor={PART.gold.light} />
          <stop offset="1" stopColor={PART.gold.dark} />
        </radialGradient>
        {compact ? null : (
          <>
            <filter id={ref("glow")} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation={LIGHT.glowBlur} />
            </filter>
            <filter id={ref("shadow")} x="-20%" y="-200%" width="140%" height="500%">
              <feGaussianBlur stdDeviation={LIGHT.shadow.soft.blur} />
            </filter>
          </>
        )}
      </defs>

      <g data-layer="shadow">
        {compact ? null : (
          <ellipse
            cx={LIGHT.shadow.cx}
            cy={LIGHT.shadow.cy}
            rx={LIGHT.shadow.soft.rx}
            ry={LIGHT.shadow.soft.ry}
            fill="#000"
            opacity={LIGHT.shadow.soft.opacity}
            filter={url("shadow")}
            data-shadow="soft"
          />
        )}
        <ellipse
          cx={LIGHT.shadow.cx}
          cy={LIGHT.shadow.cy}
          rx={LIGHT.shadow.rx}
          ry={LIGHT.shadow.ry}
          fill="#000"
          opacity={LIGHT.shadow.opacity}
          data-shadow="core"
        />
      </g>

      <g
        data-part="head"
        transform={state === "error" ? `rotate(${LIGHT.errorTilt} ${tiltX} ${tiltY})` : undefined}
      >
        <Ears def={def} paint={paint} hide={accessory.hideEars} />
        {accessory.back?.(def, paint)}
        <AntennaPart kind={look.antenna} def={def} paint={paint} advisor={advisor} />

        <g data-layer="shell">
          <Geometry
            shape={def.head}
            fill={url("shell")}
            stroke={mix(look.shell, "#000000", LIGHT.outline.darken)}
            strokeOpacity={LIGHT.outline.opacity}
            strokeWidth={LIGHT.outline.width}
          />
        </g>
        {gloss ? (
          <>
            <g data-layer="specular">
              <Geometry shape={def.head} fill={url("specular")} />
              <ellipse
                cx={LIGHT.glint.cx}
                cy={glintY}
                rx={LIGHT.glint.rx}
                ry={LIGHT.glint.ry}
                fill="#fff"
                opacity={LIGHT.glint.opacity}
                transform={`rotate(${LIGHT.glint.rotate} ${LIGHT.glint.cx} ${glintY})`}
              />
            </g>
            <g data-layer="rim">
              <Geometry shape={def.head} fill="none" stroke={url("rim")} strokeWidth={LIGHT.rim.width} />
            </g>
          </>
        ) : null}
        <Details def={def} paint={paint} />
        {accessory.face?.(def, paint)}

        <g data-layer="screen">
          {accessory.rim?.(def, paint)}
          <Geometry shape={def.screen} fill={url("screen")} />
          <Geometry shape={def.screen} fill={url("screen-shade")} />
          <Geometry
            shape={
              def.screen.kind === "circle"
                ? { ...def.screen, r: def.screen.r - LIGHT.screenEdge.inset }
                : {
                    ...def.screen,
                    x: def.screen.x + LIGHT.screenEdge.inset,
                    y: def.screen.y + LIGHT.screenEdge.inset,
                    w: def.screen.w - LIGHT.screenEdge.inset * 2,
                    h: def.screen.h - LIGHT.screenEdge.inset * 2,
                    r: def.screen.r - LIGHT.screenEdge.inset,
                  }
            }
            fill="none"
            stroke="#fff"
            strokeOpacity={LIGHT.screenEdge.opacity}
          />
        </g>
        {compact ? null : (
          <path
            data-layer="sheen"
            d={`M${screenBox.x + LIGHT.sheen.inset} ${screenBox.y + LIGHT.sheen.inset}q${screenBox.w * 0.3} -3 ${screenBox.w * 0.45} 0`}
            stroke="#fff"
            strokeOpacity={LIGHT.sheen.opacity}
            strokeWidth={LIGHT.sheen.width}
            fill="none"
            strokeLinecap="round"
          />
        )}
        {accessory.lens?.(def, paint)}
        <Eyes def={def} kind={look.eyes} state={state} paint={paint} secondEye={accessory.secondEye} />
        <Extras def={def} state={state} paint={paint} chart={Boolean(accessory.chart)} />
        {accessory.over?.(def, paint)}
      </g>

      {state === "sleeping" ? (
        <g data-part="sleep" fontFamily="ui-sans-serif, system-ui, sans-serif" fontWeight={700}>
          {SLEEP_Z.map((z, i) => (
            <text key={i} x={z.x} y={z.y} fontSize={z.size} opacity={z.opacity} fill={mix(look.shell, "#000000", z.darken)}>
              z
            </text>
          ))}
        </g>
      ) : null}
    </svg>
  )
}
