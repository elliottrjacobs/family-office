import * as React from "react"
import { CircleAlert, CircleCheck, FolderOpen, Loader2, ShieldCheck, Terminal, TriangleAlert } from "lucide-react"
import { cn } from "cn"

import { ApiError } from "@/api/client"
import { chooseOffice, type Onboarding } from "@/api/office"
import { useAppData } from "@/app-data"
import { CommandLine } from "@/components/command-line"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { moment } from "@/lib/format"

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
      This page moves on by itself once the step finishes in your terminal.
    </p>
  )
}

function TerminalOnly() {
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
      Credentials and provider consent stay in your terminal; this page never asks for them.
    </p>
  )
}

// In these states the commands are alternatives, not a sequence.
const CHOICES = new Set(["uninitialized_path", "unconnected"])

function Steps({ data }: { data: Onboarding }) {
  const choice = CHOICES.has(data.state) && data.steps.length > 1
  return (
    <div className="space-y-2">
      {choice && <p className="text-sm font-medium">Run one of these in a terminal:</p>}
      <ul className="space-y-3">
        {data.steps.map((step) => (
          <li key={step.command} className="space-y-1.5">
            <p className="text-sm">{step.purpose}</p>
            <CommandLine command={step.command} />
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
            <Terminal className="size-4" />
          </span>
          <h1 className="text-2xl">{TITLES[data.state]}</h1>
          <p className="text-sm text-muted-foreground">{data.reason}</p>
        </div>
        {data.state === "no_office" ? (
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
        <TerminalOnly />
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
          <Terminal className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
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
              {item.command ? (
                <CommandLine command={item.command} />
              ) : (
                item.hint && <p className="text-xs text-muted-foreground">{item.hint}</p>
              )}
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
      {!stale && <TerminalOnly />}
    </section>
  )
}
