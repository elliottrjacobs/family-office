/** Sync now: refresh every connected account from the page, with what each provider said. */

import * as React from "react"
import { CircleAlert, CircleCheck, Loader2, RefreshCw } from "lucide-react"

import { ApiError } from "@/api/client"
import { sync, type SyncOutcome } from "@/api/office"
import { useAppData } from "@/app-data"
import { Button } from "@/components/ui/button"
import { titleCase } from "@/lib/format"

/** Plain words for the refusals a person can do something about. */
const REFUSALS: Record<string, string> = {
  no_accounts: "No accounts are connected yet. Connect one first.",
  not_writer: "Another computer is set to sync this office, so this one does not.",
  run_active: "An advisor is working. Sync when it finishes.",
  sync_active: "A sync is already running.",
  office_locked: "The office is busy. Try again in a moment.",
  sync_timeout: "The sync took too long. Try again.",
}

export interface SyncState {
  busy: boolean
  outcomes: SyncOutcome[] | undefined
  error: string | undefined
  run: () => Promise<void>
}

export function useSync(): SyncState {
  const { refresh } = useAppData()
  const [busy, setBusy] = React.useState(false)
  const [outcomes, setOutcomes] = React.useState<SyncOutcome[]>()
  const [error, setError] = React.useState<string>()
  const run = React.useCallback(async () => {
    setBusy(true)
    setError(undefined)
    setOutcomes(undefined)
    try {
      setOutcomes((await sync()).providers)
    } catch (reason) {
      setError(
        reason instanceof ApiError ? (REFUSALS[reason.reason] ?? reason.message) : "The sync could not start."
      )
    } finally {
      setBusy(false)
      refresh()
    }
  }, [refresh])
  return { busy, outcomes, error, run }
}

/** What happened, provider by provider; nothing before the first sync. */
export function SyncResult({ state }: { state: SyncState }) {
  if (state.error) {
    return (
      <p role="alert" className="flex items-start gap-2 text-sm text-destructive-foreground">
        <CircleAlert className="mt-0.5 size-4 shrink-0" />
        {state.error}
      </p>
    )
  }
  if (!state.outcomes) return null
  return (
    <ul className="space-y-1 text-sm" aria-label="Sync results">
      {state.outcomes.map((row, index) => (
        <li key={`${row.provider}-${index}`} className="flex items-start gap-2">
          {row.status === "complete" ? (
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-success-foreground" />
          ) : (
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-warning-foreground" />
          )}
          <span>
            {titleCase(row.provider ?? "sync")}:{" "}
            {row.status === "complete" ? "up to date" : (row.message ?? row.reason ?? row.status)}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function SyncButton({ state, size = "sm" }: { state: SyncState; size?: "sm" | "default" }) {
  return (
    <Button variant="outline" size={size} onClick={() => void state.run()} disabled={state.busy}>
      {state.busy ? <Loader2 className="animate-spin" /> : <RefreshCw />}
      {state.busy ? "Syncing…" : "Sync now"}
    </Button>
  )
}
