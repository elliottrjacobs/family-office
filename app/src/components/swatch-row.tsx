// Round colour swatches with a ring on the selected one, and a rainbow swatch that reveals
// a native colour input for any other colour (U20).

import * as React from "react"
import { cn } from "cn"

import { type Hex, isHex, SWATCHES } from "@/avatars/appearance"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

/** Names for default shells that are not swatches. */
const EXTRA_NAMES: Record<string, string> = { "#C8743E": "Terracotta" }

/** The name of a shell colour: its swatch, a known default, or "Custom". */
export function colorName(hex: Hex): string {
  const upper = hex.toUpperCase()
  return SWATCHES.find((s) => s.hex === upper)?.name ?? EXTRA_NAMES[upper] ?? "Custom"
}

/**
 * Arrow-key handling for a radiogroup with a roving tab stop: Right and Down move to the
 * next option, Left and Up to the previous one, Home and End to the ends.
 */
export function radioKeyDown(event: React.KeyboardEvent, index: number, count: number, move: (next: number) => void) {
  const steps: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }
  let next: number | null = null
  if (event.key in steps) next = (index + steps[event.key] + count) % count
  else if (event.key === "Home") next = 0
  else if (event.key === "End") next = count - 1
  if (next === null) return
  event.preventDefault()
  move(next)
}

const RAINBOW =
  "conic-gradient(from 180deg, #E5484D, #F07A2B, #E3A21A, #7C9A2E, #1F9D63, #0EA5B7, #2E9CEB, #6457F0, #A94FD6, #E84593, #E5484D)"

/** The ring on a selected swatch: a gap in the page colour, then the foreground. */
export const SELECTED_RING = "outline-2 outline-offset-2 outline-solid outline-foreground"

export function SwatchRow({
  value,
  onChange,
  label = "Color",
  size = "md",
  className,
}: {
  value: Hex
  onChange: (value: Hex) => void
  label?: string
  /** md is 24 px swatches (the Mac inspector), lg is 36 px (the phone sheet). */
  size?: "md" | "lg"
  className?: string
}) {
  const refs = React.useRef<(HTMLButtonElement | null)[]>([])
  const inputId = React.useId()
  const upper = value.toUpperCase()
  const matched = SWATCHES.findIndex((s) => s.hex === upper)
  // The custom swatch stays chosen after a click until a preset is picked, even before
  // the colour input changes anything.
  const [customChosen, setCustomChosen] = React.useState(false)
  const custom = matched < 0 || customChosen
  const count = SWATCHES.length + 1
  const selected = custom ? SWATCHES.length : matched

  const pick = (index: number) => {
    if (index < SWATCHES.length) {
      setCustomChosen(false)
      onChange(SWATCHES[index].hex)
    } else {
      setCustomChosen(true)
    }
  }
  const move = (index: number) => {
    pick(index)
    refs.current[index]?.focus()
  }

  // On the phone the swatches share the width in rows of eight, up to 40 px each.
  const dimension = size === "lg" ? "aspect-square w-full max-w-10 justify-self-center" : "size-6"
  const swatch = (index: number, name: string, background: string) => {
    const checked = index === selected
    return (
      <Tooltip key={name}>
        <TooltipTrigger
          render={
            <button
              ref={(element) => {
                refs.current[index] = element
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              aria-label={name}
              tabIndex={checked ? 0 : -1}
              data-swatch={name}
              onClick={() => pick(index)}
              onKeyDown={(event) => radioKeyDown(event, index, count, move)}
              className={cn(
                dimension,
                "shrink-0 rounded-full shadow-[inset_0_0_0_1px_rgb(0_0_0/0.08)] transition-transform outline-none hover:scale-105 focus-visible:ring-3 focus-visible:ring-ring/50 dark:shadow-[inset_0_0_0_1px_rgb(255_255_255/0.12)]",
                checked && SELECTED_RING
              )}
              style={{ background }}
            />
          }
        />
        <TooltipContent>{name}</TooltipContent>
      </Tooltip>
    )
  }

  return (
    <div className={cn("space-y-3", className)}>
      <div
        role="radiogroup"
        aria-label={label}
        className={cn(size === "lg" ? "grid grid-cols-8 gap-2.5" : "flex flex-wrap gap-2")}
      >
        {SWATCHES.map((s, index) => swatch(index, s.name, s.hex))}
        {swatch(SWATCHES.length, "Custom color", RAINBOW)}
      </div>
      {custom && (
        <label htmlFor={inputId} className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            id={inputId}
            type="color"
            value={isHex(value) ? value.toLowerCase() : "#000000"}
            onChange={(event) => onChange(event.target.value.toUpperCase())}
            className="h-7 w-10 cursor-pointer rounded-md border bg-transparent p-0.5"
          />
          <span>
            Custom color <span className="font-mono text-foreground">{upper}</span>
          </span>
        </label>
      )}
    </div>
  )
}
