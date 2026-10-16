import * as React from "react"
import { CircleAlert, Loader2, Undo2 } from "lucide-react"

import { ApiError } from "@/api/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

/** Friendlier words for the conflicts a person can actually cause. */
const CONFLICTS: Record<string, string> = {
  invalid_transition: "This decision was already closed or reopened, perhaps in another tab.",
  office_locked: "Another fo command holds the office lock. Wait a moment and try again.",
  run_active: "An advisor run is in progress. Wait for it to finish, then try again.",
}

export function message(error: unknown) {
  if (error instanceof ApiError) return CONFLICTS[error.reason] ?? error.message
  return "The action failed."
}

/**
 * Every write asks first and says how to undo it. `onConfirm` returns false to keep the
 * dialog open when its own fields explain the problem; any error stays in the dialog so
 * the person can read it.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  rollback,
  confirm,
  onConfirm,
  disabled,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: React.ReactNode
  rollback: string
  confirm: string
  onConfirm: () => Promise<void | false>
  disabled?: boolean
  children?: React.ReactNode
}) {
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string>()
  const run = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      if ((await onConfirm()) !== false) onOpenChange(false)
    } catch (reason) {
      setError(message(reason))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(undefined)
        onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={run} className="space-y-4" noValidate>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && <DialogDescription>{description}</DialogDescription>}
          </DialogHeader>
          {children}
          <p className="flex items-start gap-2 rounded-lg bg-muted/60 p-2.5 text-xs text-muted-foreground">
            <Undo2 className="mt-0.5 size-3.5 shrink-0" />
            {rollback}
          </p>
          {error && (
            <p role="alert" className="flex items-start gap-2 text-sm text-destructive-foreground">
              <CircleAlert className="mt-0.5 size-4 shrink-0" />
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || disabled}>
              {busy && <Loader2 className="animate-spin" />}
              {confirm}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
