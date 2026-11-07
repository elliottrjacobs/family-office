// An advisor's robot where it has one, its icon where it does not, and the shared view of
// the conversation the robots follow (U19).

import * as React from "react"
import { cn } from "cn"

import type { Group } from "@/api/office"
import type { Run, RunEvent } from "@/api/runs"
import { useAppData } from "@/app-data"
import { type AdvisorId, advisorIdFor } from "@/avatars/appearance"
import { Robot } from "@/avatars/Robot"
import { type AvatarState, useAvatarState, useSpeakingLevel } from "@/avatars/states"
import { AdvisorIcon } from "@/components/advisor-icon"

export interface LiveRun {
  run: Run | undefined
  events: readonly RunEvent[]
}

// The open conversation per advisor, published by the chat so the header and the sidebar
// follow the same stream without opening their own.
const published = new Map<AdvisorId, LiveRun>()
const listeners = new Set<() => void>()

export function publishRun(advisor: AdvisorId, value: LiveRun | null) {
  if (value) published.set(advisor, value)
  else published.delete(advisor)
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useLiveRun(advisor: AdvisorId | null): LiveRun | undefined {
  return React.useSyncExternalStore(
    subscribe,
    () => (advisor ? published.get(advisor) : undefined),
    () => undefined
  )
}

const NO_EVENTS: readonly RunEvent[] = []

/** The state and speaking level of an advisor's robot, from the published conversation or `fallback`. */
export function useAdvisorState(advisor: AdvisorId | null, fallback?: Run): { state: AvatarState; level: number } {
  const { connected } = useAppData()
  const live = useLiveRun(advisor)
  const events = live?.events ?? NO_EVENTS
  const state = useAvatarState(live?.run ?? fallback, events, connected)
  const level = useSpeakingLevel(events)
  return { state, level: state === "speaking" ? level : 0 }
}

export const STATE_LABELS: Record<AvatarState, string> = {
  idle: "Idle",
  thinking: "Thinking",
  reading: "Reading",
  writing: "Writing",
  speaking: "Speaking",
  done: "Done",
  error: "Error",
  sleeping: "Offline",
}

/** A static robot for a skill with one, otherwise its icon. */
export function AdvisorAvatar({
  name,
  group,
  size = 24,
  state,
  className,
}: {
  name: string
  group: Group
  size?: number
  state?: AvatarState
  className?: string
}) {
  const advisor = advisorIdFor(name)
  if (!advisor) return <AdvisorIcon name={name} group={group} className={className} />
  return <Robot advisor={advisor} size={size} state={state} className={cn("shrink-0", className)} />
}

/** A robot that follows the advisor's conversation; `label` adds the state name beneath it. */
export function LiveAdvisorAvatar({
  advisor,
  size,
  fallback,
  label = false,
  className,
}: {
  advisor: AdvisorId
  size: number
  fallback?: Run
  label?: boolean
  className?: string
}) {
  const { state, level } = useAdvisorState(advisor, fallback)
  const robot = <Robot advisor={advisor} size={size} state={state} level={level} live className={cn("shrink-0", className)} />
  if (!label) return robot
  return (
    <span className="inline-flex shrink-0 flex-col items-center gap-0.5">
      {robot}
      <span className="text-[10px] leading-none text-muted-foreground" data-avatar-label>
        {state === "idle" ? " " : STATE_LABELS[state]}
      </span>
    </span>
  )
}
