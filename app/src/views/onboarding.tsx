import * as React from "react"
import {
  CircleAlert,
  CircleCheck,
  FolderOpen,
  Loader2,
  MessageSquare,
  Settings2,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react"
import { cn } from "cn"

import { ApiError } from "@/api/client"
import { chooseOffice, type Onboarding, type StepAction } from "@/api/office"
import { useAppData } from "@/app-data"
import { CommandLine } from "@/components/command-line"
import { SyncButton, SyncResult, useSync } from "@/components/sync-button"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { moment } from "@/lib/format"
import { hasNative, native, stepButton, stepPlace } from "@/lib/native"
import { Link } from "@/lib/router"

const TITLES: Record<string, string> = {
  no_office: "Set up your family office",
  uninitialized_path: "Create the office",
  unconnected: "Connect your accounts",
  offline: "Import your exports",
  never_synced: "Run the first sync",
  stale: "Needs attention",
  ready: "All set",
}

function Waiting() {
  return (
    <p className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />
      This page moves on by itself once the step is done.
    </p>
  )
}

function CredentialsNote() {
  const { status } = useAppData()
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
      {status?.app
        ? "Account credentials are entered in the Mac app's own windows; this page never asks for them."
        : "Credentials and provider consent stay in your terminal; this page never asks for them."}
    </p>
  )
}

// In these states the commands are alternatives, not a sequence.
const CHOICES = new Set(["uninitialized_path", "unconnected"])

/**
 * How to do one step without leaving the app when that is possible: a sync from this
 * page, the interview with Onboard, or a button that opens the Mac app's own window.
 * Otherwise where it lives on the Mac, or the terminal command.
 */
export function StepAct({
  action,
  command,
}: {
  action: StepAction | undefined
  command: string | null
}) {
  const { status } = useAppData()
  const syncing = useSync()
  if (action === "sync" && status?.chat) {
    return (
      <div className="space-y-2">
        <SyncButton state={syncing} />
        <SyncResult state={syncing} />
      </div>
    )
  }
  if (action === "onboard") {
    return (
      <Button variant="outline" size="sm" render={<Link to="/advisors/onboard" />}>
        <MessageSquare /> Open Onboard
      </Button>
    )
  }
  const button = stepButton(action)
  if (button && hasNative()) {
    return (
      <Button variant="outline" size="sm" onClick={() => native(button.action)}>
        {button.action === "setup" ? <Sparkles /> : <Settings2 />} {button.label}
      </Button>
    )
  }
  const place = status?.app ? stepPlace(action) : null
  if (place) return <p className="text-xs text-muted-foreground">{place}</p>
  return command ? <CommandLine command={command} /> : null
}

function Steps({ data }: { data: Onboarding }) {
  const { status } = useAppData()
  const choice = CHOICES.has(data.state) && data.steps.length > 1
  // The Mac app's Connectors pane lists every provider, so one button covers them all.
  const inApp = hasNative() || Boolean(status?.app)
  const steps = inApp
    ? data.steps.filter(
        (step, index) =>
          !stepButton(step.action) ||
          data.steps.findIndex((s) => stepButton(s.action)?.action === stepButton(step.action)?.action) === index
      )
    : data.steps
  const visible = inApp && data.state === "uninitialized_path" ? steps.slice(0, 1) : steps
  return (
    <div className="space-y-2">
      {choice && !inApp && <p className="text-sm font-medium">Run one of these in a terminal:</p>}
      <ul className="space-y-3">
        {visible.map((step) => (
          <li key={step.command} className="space-y-1.5">
            <p className="text-sm">
              {inApp && step.action?.startsWith("connect") && data.state === "unconnected"
                ? "Connect Schwab or SimpleFIN in the Connectors settings."
                : inApp && step.action === "setup"
                  ? "Create the office with the setup guide."
                  : step.purpose}
            </p>
            <StepAct action={step.action} command={step.command} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function ChooseFolder() {
  const { refresh } = useAppData()
  const [path, setPath] = React.useState("")
  const [error, setError] = React.useState<string>()
  const [busy, setBusy] = React.useState(false)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      await chooseOffice(path)
      refresh()
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "That folder cannot be used.")
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={submit} className="space-y-2">
      <label htmlFor="office-path" className="text-sm font-medium">
        Where should the office live?
      </label>
      <div className="flex gap-2">
        <Input
          id="office-path"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder="~/family-office"
          autoComplete="off"
          spellCheck={false}
          className="font-mono"
          aria-invalid={Boolean(error)}
        />
        <Button type="submit" disabled={busy || !path.trim()}>
          {busy ? <Loader2 className="animate-spin" /> : <FolderOpen />} Use folder
        </Button>
      </div>
      {error ? (
        <p role="alert" className="flex items-center gap-1.5 text-sm text-destructive-foreground">
          <CircleAlert className="size-4" /> {error}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          An empty or new folder outside any Git repository and outside synced drives. Nothing
          is created until you run the command shown next.
        </p>
      )}
    </form>
  )
}

/** Full page for the states with no office to show yet. */
export function OnboardingPage({ data }: { data: Onboarding }) {
  return (
    <div className="flex min-h-svh items-start justify-center bg-sidebar px-4 py-12 sm:items-center">
      <div className="w-full max-w-xl space-y-6 rounded-2xl border bg-background p-6 shadow-sm sm:p-8">
        <div className="space-y-2">
          <span className="inline-flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Sparkles className="size-4" />
          </span>
          <h1 className="text-2xl">{TITLES[data.state]}</h1>
          <p className="text-sm text-muted-foreground">{data.reason}</p>
        </div>
        {data.state === "no_office" && hasNative() ? (
          <div className="space-y-2">
            <p className="text-sm">The setup guide creates the office folder and connects your accounts.</p>
            <Button onClick={() => native("setup")}>
              <Sparkles /> Open setup
            </Button>
          </div>
        ) : data.state === "no_office" ? (
          <ChooseFolder />
        ) : (
          <div className="space-y-4">
            <p className="text-sm">
              Folder: <code className="font-mono text-xs break-all">{data.candidate}</code>
            </p>
            <Steps data={data} />
            <Waiting />
          </div>
        )}
        <CredentialsNote />
      </div>
    </div>
  )
}

/** The next step on Home while the office is being connected, synced, or repaired. */
export function SetupCard({ data }: { data: Onboarding }) {
  const stale = data.state === "stale"
  return (
    <section
      className={cn(
        "space-y-4 rounded-xl border p-4 sm:p-5",
        stale ? "border-warning/40 bg-warning/5" : "bg-card"
      )}
    >
      <div className="flex items-start gap-3">
        {stale ? (
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-warning-foreground" />
        ) : (
          <Sparkles className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
        )}
        <div className="space-y-1">
          <h2 className="text-base font-semibold">{TITLES[data.state]}</h2>
          <p className="text-sm text-muted-foreground">{data.reason}</p>
        </div>
      </div>
      {data.providers.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {data.providers.map((p) => (
            <Badge key={p.provider} variant="outline" className="gap-1.5">
              {p.connected ? (
                <CircleCheck className="text-success-foreground" />
              ) : (
                <CircleAlert className="text-warning-foreground" />
              )}
              {p.provider} · {p.accounts} {p.accounts === 1 ? "account" : "accounts"}
            </Badge>
          ))}
        </div>
      )}
      {stale ? (
        <ul className="space-y-3">
          {data.doctor.map((item) => (
            <li key={item.name} className="space-y-1.5">
              <p className="flex items-start gap-2 text-sm">
                <Badge variant={item.status === "fail" ? "destructive" : "outline"} className="mt-px">
                  {item.status}
                </Badge>
                <span>
                  {item.reason}
                  <span className="ml-1.5 font-mono text-xs text-muted-foreground">{item.name}</span>
                </span>
              </p>
              {!item.command && item.hint && <p className="text-xs text-muted-foreground">{item.hint}</p>}
              <StepAct action={item.action} command={item.command} />
            </li>
          ))}
        </ul>
      ) : (
        <Steps data={data} />
      )}
      {data.note && <p className="text-sm text-muted-foreground">{data.note}</p>}
      {!stale && <Waiting />}
      {data.last_sync && (
        <p className="text-xs text-muted-foreground">Last complete sync {moment(data.last_sync)}.</p>
      )}
      {!stale && <CredentialsNote />}
    </section>
  )
}
