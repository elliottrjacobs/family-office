import { cn } from "cn"

import { Badge } from "@/components/ui/badge"
import { percent } from "@/lib/format"

export type BandState = "inside" | "above" | "below" | "unknown"

export function bandState(weight: number | null, min: number, max: number): BandState {
  if (weight === null) return "unknown"
  if (weight > max) return "above"
  if (weight < min) return "below"
  return "inside"
}

const FILL: Record<BandState, string> = {
  inside: "bg-foreground/70",
  above: "bg-destructive",
  below: "bg-warning",
  unknown: "bg-transparent",
}

/** A weight drawn against its policy band, on a scale that leaves room past the band. */
export function AllocationBar({
  name,
  weight,
  min,
  max,
}: {
  name: string
  weight: number | null
  min: number
  max: number
}) {
  const state = bandState(weight, min, max)
  const scale = Math.min(1, Math.max(0.1, Math.ceil(Math.max(weight ?? 0, max) * 1.25 * 20) / 20))
  const at = (value: number) => `${Math.min(100, (value / scale) * 100)}%`
  return (
    <div data-state={state} className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="truncate font-medium">{name}</span>
        <span className="flex items-center gap-2">
          {state === "above" && <Badge variant="destructive">Over band</Badge>}
          {state === "below" && (
            <Badge className="bg-warning/15 text-warning-foreground">Under band</Badge>
          )}
          <span
            className={cn(
              "font-mono tabular-nums",
              state === "above" && "text-destructive-foreground",
              state === "below" && "text-warning-foreground",
              state === "unknown" && "text-muted-foreground"
            )}
          >
            {percent(weight)}
          </span>
        </span>
      </div>
      <div
        className="relative h-2 rounded-full bg-muted"
        role="img"
        aria-label={`${name}: ${percent(weight)}, policy ${percent(min, 0)} to ${percent(max, 0)}`}
      >
        {weight !== null && (
          <div
            className={cn("absolute inset-y-0 left-0 rounded-full", FILL[state])}
            style={{ width: at(weight) }}
          />
        )}
        {/* The band sits over the fill so it stays visible where they overlap. */}
        <div
          className="absolute inset-y-0 rounded-full bg-success/35 ring-1 ring-success/50"
          style={{ left: at(min), width: `calc(${at(max)} - ${at(min)})` }}
        />
        {weight !== null && (
          <div
            className={cn(
              "absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background",
              FILL[state]
            )}
            style={{ left: at(weight) }}
          />
        )}
      </div>
      <div className="relative h-4 font-mono text-[0.7rem] text-muted-foreground">
        <span className="absolute -translate-x-1/2" style={{ left: at(min) }}>
          {percent(min, 0)}
        </span>
        <span className="absolute -translate-x-1/2" style={{ left: at(max) }}>
          {percent(max, 0)}
        </span>
      </div>
    </div>
  )
}
