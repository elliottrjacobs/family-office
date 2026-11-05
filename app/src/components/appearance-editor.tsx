// The robot customize body shared by the Mac inspector and the phone sheet (U20). Every
// edit is saved at once through the avatar store, so every mounted robot for the advisor
// follows it.

import * as React from "react"
import { ChevronDown, RotateCcw } from "lucide-react"
import { cn } from "cn"

import {
  ADVISORS,
  type AdvisorId,
  ANTENNAS,
  type Appearance,
  defaultAppearance,
  EYE_KINDS,
  FINISHES,
  GENERIC_SHAPES,
  glowColors,
  type Hex,
  isDefault,
  isHex,
  type RobotState,
  SCREEN_PRESETS,
  SCREENS,
  type Shape,
  SPEED,
  TRIM_PRESETS,
  TRIMS,
} from "@/avatars/appearance"
import { Robot } from "@/avatars/Robot"
import { resetAppearance, saveAppearance, useAppearance } from "@/avatars/store"
import { STATE_LABELS } from "@/components/advisor-avatar"
import { Segmented } from "@/components/segmented"
import { colorName, radioKeyDown, SwatchRow } from "@/components/swatch-row"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { titleCase } from "@/lib/format"

export type EditorSize = "mac" | "phone"

/** The advisor's look and a setter that saves each change immediately. */
export function useAppearanceEditor(advisorId: AdvisorId) {
  const look = useAppearance(advisorId)
  const update = React.useCallback(
    (change: Partial<Appearance>) => saveAppearance(advisorId, { ...look, ...change }),
    [advisorId, look]
  )
  return { look, update }
}

const ACTIVE: ReadonlySet<RobotState> = new Set(["thinking", "reading", "writing", "speaking", "done"])

/** A small status pill: green while the advisor works or has just finished. */
export function StatePill({ state, children }: { state: RobotState; children?: React.ReactNode }) {
  const tone = ACTIVE.has(state)
    ? "text-success-foreground"
    : state === "error"
      ? "text-destructive-foreground"
      : "text-muted-foreground"
  const dot = ACTIVE.has(state) ? "bg-success" : state === "error" ? "bg-destructive" : "bg-muted-foreground/50"
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full bg-background/90 px-2.5 py-0.5 text-xs font-medium shadow-sm ring-1 ring-black/5 backdrop-blur dark:bg-background/80 dark:ring-white/10",
        tone
      )}
      data-state-pill
    >
      {children ?? (
        <>
          <span className={cn("size-1.5 rounded-full", dot)} aria-hidden />
          {STATE_LABELS[state]}
        </>
      )}
    </span>
  )
}

/** The tinted card with the live robot and either the state pill or a caption. */
export function AppearancePreview({
  advisorId,
  size = "mac",
  state = "idle",
  level = 0,
  caption,
  className,
}: {
  advisorId: AdvisorId
  size?: EditorSize
  state?: RobotState
  level?: number
  caption?: React.ReactNode
  className?: string
}) {
  const look = useAppearance(advisorId)
  return (
    <div
      className={cn(
        "relative flex flex-col items-center justify-center overflow-hidden rounded-2xl pt-5 pb-3",
        className
      )}
      style={{
        background: `radial-gradient(ellipse at 50% 40%, color-mix(in oklch, ${look.shell} 16%, var(--card)), color-mix(in oklch, ${look.shell} 6%, var(--muted)))`,
      }}
      data-preview
    >
      <Robot advisor={advisorId} size={size === "phone" ? 140 : 120} state={state} level={level} live />
      <div className="-mt-1" aria-live="polite">
        {caption ? <StatePill state="idle">{caption}</StatePill> : <StatePill state={state} />}
      </div>
    </div>
  )
}

function Field({ label, children, id }: { label: string; children: React.ReactNode; id?: string }) {
  return (
    <div className="space-y-2">
      <p id={id} className="text-xs font-semibold text-foreground">
        {label}
      </p>
      {children}
    </div>
  )
}

type PillOption<T extends string> = { value: T; label: string; dot?: string }

/** Wrapping pills as a radiogroup; the last pill may be a custom colour that reveals a colour input. */
function Pills<T extends string>({
  label,
  options,
  value,
  onChange,
  custom,
  size,
}: {
  label: string
  options: PillOption<T>[]
  value: string
  onChange: (value: string) => void
  /** Adds a Custom pill holding any hex; `fallback` seeds its colour input. */
  custom?: { fallback: Hex }
  size: EditorSize
}) {
  const refs = React.useRef<(HTMLButtonElement | null)[]>([])
  const inputId = React.useId()
  const [customChosen, setCustomChosen] = React.useState(false)
  const isCustom = Boolean(custom) && (isHex(value) || customChosen)
  const all: PillOption<string>[] = custom
    ? [...options, { value: "custom", label: "Custom", dot: "conic-gradient(#E5484D, #E3A21A, #1F9D63, #2E9CEB, #A94FD6, #E5484D)" }]
    : options
  const selected = isCustom ? all.length - 1 : all.findIndex((o) => o.value === value)
  const pick = (index: number) => {
    const option = all[index]
    if (custom && option.value === "custom") {
      setCustomChosen(true)
      return
    }
    setCustomChosen(false)
    onChange(option.value)
  }
  const move = (index: number) => {
    pick(index)
    refs.current[index]?.focus()
  }
  return (
    <div className="space-y-2.5">
      <div role="radiogroup" aria-label={label} className={cn("flex flex-wrap", size === "phone" ? "gap-2" : "gap-1.5")}>
        {all.map((option, index) => {
          const checked = index === selected
          return (
            <button
              key={option.value}
              ref={(element) => {
                refs.current[index] = element
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={checked || (selected < 0 && index === 0) ? 0 : -1}
              onClick={() => pick(index)}
              onKeyDown={(event) => radioKeyDown(event, index, all.length, move)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-xl border border-transparent bg-muted font-medium text-foreground/80 transition-colors outline-none hover:bg-muted/70 focus-visible:ring-3 focus-visible:ring-ring/50",
                size === "phone" ? "h-9 px-3.5 text-sm" : "h-7 px-2.5 text-xs",
                checked && "border-foreground bg-background text-foreground shadow-sm dark:bg-input/30"
              )}
            >
              {option.dot && (
                <span
                  className="size-2.5 shrink-0 rounded-full shadow-[inset_0_0_0_1px_rgb(0_0_0/0.12)]"
                  style={{ background: option.dot }}
                  aria-hidden
                />
              )}
              {option.label}
            </button>
          )
        })}
      </div>
      {custom && isCustom && (
        <label htmlFor={inputId} className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            id={inputId}
            type="color"
            value={(isHex(value) ? value : custom.fallback).toLowerCase()}
            onChange={(event) => onChange(event.target.value.toUpperCase())}
            className="h-7 w-10 cursor-pointer rounded-md border bg-transparent p-0.5"
          />
          <span>Custom {label.toLowerCase()}</span>
        </label>
      )}
    </div>
  )
}

const EYE_LABELS: Record<(typeof EYE_KINDS)[number], string> = {
  pill: "Pill",
  dot: "Dot",
  square: "Square",
  ring: "Ring",
  bar: "Bar",
}

function shapeLabel(shape: Shape, advisorId: AdvisorId): string {
  if (shape === advisorId) return `${ADVISORS[advisorId].name} (own)`
  if (shape in ADVISORS) return ADVISORS[shape as AdvisorId].name
  return titleCase(shape)
}

function speedLabel(speed: number): string {
  return speed === 0 ? "Paused" : `${Number(speed.toFixed(2))}×`
}

/** Color, Screen glow and the More section, then the reset line. */
export function AppearanceControls({
  advisorId,
  size = "mac",
  className,
}: {
  advisorId: AdvisorId
  size?: EditorSize
  className?: string
}) {
  const { look, update } = useAppearanceEditor(advisorId)
  const fallback = defaultAppearance(advisorId)
  const speedId = React.useId()
  const shapes: Shape[] = [advisorId, ...GENERIC_SHAPES]
  if (!shapes.includes(look.shape)) shapes.splice(1, 0, look.shape)
  const gap = size === "phone" ? "space-y-5" : "space-y-4"

  return (
    <div className={cn(gap, className)}>
      <Field label="Color">
        <SwatchRow value={look.shell} onChange={(shell) => update({ shell })} size={size === "phone" ? "lg" : "md"} />
      </Field>
      <Field label="Screen glow">
        <Pills
          label="Screen glow"
          size={size}
          value={look.screen}
          onChange={(screen) => update({ screen })}
          custom={{ fallback: glowColors(look).eye }}
          options={SCREEN_PRESETS.map((preset) => ({
            value: preset,
            label: SCREENS[preset].name,
            dot: glowColors({ screen: preset, shell: look.shell }).eye,
          }))}
        />
      </Field>
      <Collapsible className="group/more">
        <CollapsibleTrigger
          render={
            <button
              type="button"
              className="flex w-full items-center justify-between rounded-md py-1 text-xs font-semibold text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            />
          }
        >
          More
          <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[open]/more:rotate-180" />
        </CollapsibleTrigger>
        <CollapsibleContent className={cn("pt-3", gap)}>
          <Field label="Shape">
            <Select
              value={look.shape}
              onValueChange={(shape) => shape && update({ shape: shape as Shape })}
              items={shapes.map((shape) => ({ value: shape, label: shapeLabel(shape, advisorId) }))}
            >
              <SelectTrigger aria-label="Shape" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {shapes.map((shape) => (
                  <SelectItem key={shape} value={shape}>
                    {shapeLabel(shape, advisorId)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Trim">
            <Pills
              label="Trim"
              size={size}
              value={look.trim}
              onChange={(trim) => update({ trim })}
              custom={{ fallback: "#98A2B0" }}
              options={TRIM_PRESETS.map((preset) => ({
                value: preset,
                label: TRIMS[preset].name,
                dot: `linear-gradient(${TRIMS[preset].light}, ${TRIMS[preset].dark})`,
              }))}
            />
          </Field>
          <Field label="Finish">
            <Segmented
              label="Finish"
              options={FINISHES.map((finish) => ({ value: finish, label: titleCase(finish) }))}
              value={look.finish}
              onChange={(finish) => update({ finish })}
            />
          </Field>
          <Field label="Antenna">
            <Pills
              label="Antenna"
              size={size}
              value={look.antenna}
              onChange={(antenna) => update({ antenna: antenna as Appearance["antenna"] })}
              options={ANTENNAS.map((antenna) => ({ value: antenna, label: titleCase(antenna) }))}
            />
          </Field>
          <label className="flex items-center justify-between gap-3">
            <span className="text-xs font-semibold">
              Role accessory
              <span className="block font-normal text-muted-foreground">The advisor's signature piece.</span>
            </span>
            <Switch checked={look.accessory} onCheckedChange={(accessory) => update({ accessory })} aria-label="Role accessory" />
          </label>
          <Field label="Eyes">
            <Pills
              label="Eyes"
              size={size}
              value={look.eyes}
              onChange={(eyes) => update({ eyes: eyes as Appearance["eyes"] })}
              options={EYE_KINDS.map((eyes) => ({ value: eyes, label: EYE_LABELS[eyes] }))}
            />
          </Field>
          <Field label="Animation speed" id={speedId}>
            <input
              type="range"
              min={SPEED.min}
              max={SPEED.max}
              step={0.25}
              value={look.speed}
              onChange={(event) => update({ speed: Number(event.target.value) })}
              aria-labelledby={speedId}
              aria-valuetext={speedLabel(look.speed)}
              className="w-full accent-foreground"
            />
            <div className="flex justify-between text-[11px] text-muted-foreground" aria-hidden>
              <span>Pause</span>
              <span>1×</span>
              <span>2×</span>
            </div>
          </Field>
        </CollapsibleContent>
      </Collapsible>
      {!isDefault(look, advisorId) && (
        <div className={cn(size === "phone" && "flex justify-center")}>
          <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => resetAppearance(advisorId)}>
            <RotateCcw /> Reset to {colorName(fallback.shell)}
          </Button>
        </div>
      )}
    </div>
  )
}

/** Preview and controls together: the body of the phone sheet. */
export function AppearanceEditor({
  advisorId,
  size = "mac",
  state = "idle",
  level = 0,
  caption,
}: {
  advisorId: AdvisorId
  size?: EditorSize
  state?: RobotState
  level?: number
  caption?: React.ReactNode
}) {
  return (
    <div className="space-y-5">
      <AppearancePreview advisorId={advisorId} size={size} state={state} level={level} caption={caption} />
      <AppearanceControls advisorId={advisorId} size={size} />
    </div>
  )
}
