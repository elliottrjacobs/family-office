import * as React from "react"
import { CircleAlert, LogIn, RefreshCw } from "lucide-react"
import { cn } from "cn"

import type { ApiError } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

export function Page({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8", className)}
      {...props}
    />
  )
}

export function PageTitle({
  title,
  description,
  actions,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <h1 className="text-2xl sm:text-3xl">{title}</h1>
        {description && <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mt-8 mb-3 flex items-center justify-between gap-2 first:mt-0">
      <h2 className="text-base font-semibold">{children}</h2>
      {aside}
    </div>
  )
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full rounded-xl" />
      ))}
    </div>
  )
}

export function ErrorNotice({ error, retry }: { error: ApiError; retry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm"
    >
      {error.signedOut ? (
        <LogIn className="mt-0.5 size-4 shrink-0 text-destructive-foreground" />
      ) : (
        <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive-foreground" />
      )}
      <div className="flex-1 space-y-1">
        <p className="font-medium">{error.message}</p>
        <p className="font-mono text-xs text-muted-foreground">{error.reason}</p>
      </div>
      {retry && !error.signedOut && (
        <Button variant="outline" size="sm" onClick={retry}>
          <RefreshCw /> Retry
        </Button>
      )}
    </div>
  )
}

export function Empty({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-6 py-10 text-center">
      <Icon className="size-5 text-muted-foreground" />
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  )
}

export function Stat({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: React.ReactNode
  detail?: React.ReactNode
  tone?: "warning" | "destructive"
}) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 font-heading text-2xl tabular-nums",
          tone === "warning" && "text-warning-foreground",
          tone === "destructive" && "text-destructive-foreground"
        )}
      >
        {value}
      </p>
      {detail && <p className="mt-1 text-xs text-muted-foreground">{detail}</p>}
    </div>
  )
}
