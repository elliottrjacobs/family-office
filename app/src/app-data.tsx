import * as React from "react"

import type { ApiError } from "@/api/client"
import { subscribe } from "@/api/events"
import {
  onboarding,
  type Onboarding,
  type Registry,
  review,
  type Review,
  skills,
  status,
  type Status,
} from "@/api/office"
import { useApi } from "@/api/use-api"

interface AppData {
  status: Status | undefined
  statusError: ApiError | undefined
  onboarding: Onboarding | undefined
  registry: Registry | undefined
  review: Review | undefined
  connected: boolean
  refresh: () => void
}

const Context = React.createContext<AppData | null>(null)

const SETTING_UP = new Set(["no_office", "uninitialized_path", "unconnected", "offline", "never_synced"])

export function AppDataProvider({ children }: { children: React.ReactNode }) {
  const server = useApi("status", status, 10_000)
  const setup = useApi("onboarding", onboarding, 4_000)
  const registry = useApi("skills", skills)
  const office = server.data?.mode === "office"
  const decisions = useApi(office ? "review" : "review-none", () => (office ? review() : Promise.resolve(undefined)), 30_000)
  const [connected, setConnected] = React.useState(true)

  // The heartbeat stream ends when fo serve stops; the browser retries on its own.
  React.useEffect(
    () =>
      subscribe(
        "/api/heartbeat",
        () => setConnected(true),
        () => setConnected(false)
      ),
    []
  )

  const reloadStatus = server.reload
  // A terminal step can create or open the office; refresh the server view when it does.
  const officePath = setup.data?.office
  React.useEffect(() => {
    if (officePath) reloadStatus()
  }, [officePath, reloadStatus])

  const reloadSetup = setup.reload
  const reloadReview = decisions.reload
  const refresh = React.useCallback(() => {
    reloadStatus()
    reloadSetup()
    reloadReview()
  }, [reloadStatus, reloadSetup, reloadReview])

  const value = React.useMemo<AppData>(
    () => ({
      status: server.data,
      statusError: server.error,
      onboarding: setup.data,
      registry: registry.data,
      review: decisions.data,
      connected,
      refresh,
    }),
    [server.data, server.error, setup.data, registry.data, decisions.data, connected, refresh]
  )
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useAppData() {
  const value = React.useContext(Context)
  if (!value) throw new Error("useAppData must be used inside AppDataProvider")
  return value
}

export function settingUp(state: string | undefined) {
  return state !== undefined && SETTING_UP.has(state)
}

/** Decisions the review flags for a verdict now: breached or past the verdict window. */
export function needsVerdict(review: Review | undefined) {
  return (review?.decisions ?? []).filter((d) => d.breached || d.due_for_verdict)
}
