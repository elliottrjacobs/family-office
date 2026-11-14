/** Earlier conversations, newest first: open one, or delete it. */

import * as React from "react"
import { Loader2, MessageSquare, Trash2 } from "lucide-react"
import { cn } from "cn"

import type { Advisor } from "@/api/office"
import { ACTIVE, remove, type Run } from "@/api/runs"
import { AdvisorIcon, advisorName } from "@/components/advisor-icon"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { Link } from "@/lib/router"

export const chatHref = (run: Pick<Run, "id" | "skill">) => `/advisors/${run.skill}?chat=${run.id}`

/** What a conversation is called in a list: its first message, else its subject. */
export function chatTitle(run: Run) {
  if (run.title) return run.title
  return run.subject === "household" ? `${advisorName(run.skill)} report` : `${run.subject} report`
}

function when(run: Run) {
  return run.updated ?? run.created
}

/** Today, Yesterday, Earlier this week, then by month. */
export function period(value: string, now = new Date()) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "Earlier"
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const days = Math.floor((start - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) / 86_400_000)
  if (days <= 0) return "Today"
  if (days === 1) return "Yesterday"
  if (days < 7) return "This week"
  return date.toLocaleDateString("en-US", { month: "long", year: "numeric" })
}

export function byPeriod(list: Run[], now = new Date()) {
  const groups: { label: string; runs: Run[] }[] = []
  for (const run of [...list].sort((a, b) => (when(a) < when(b) ? 1 : -1))) {
    const label = period(when(run), now)
    const last = groups[groups.length - 1]
    if (last?.label === label) last.runs.push(run)
    else groups.push({ label, runs: [run] })
  }
  return groups
}

export function ChatHistory({
  runs,
  current,
  advisors,
  onDeleted,
  onNavigate,
  empty = "No chats yet.",
}: {
  runs: Run[]
  /** The conversation on screen, marked in the list. */
  current?: string | null
  /** Pass to show which advisor each conversation is with (the all-chats list). */
  advisors?: Advisor[]
  onDeleted: (id: string) => void
  onNavigate?: () => void
  empty?: string
}) {
  const [doomed, setDoomed] = React.useState<Run | null>(null)
  if (!runs.length) {
    return (
      <p className="flex items-center gap-2 px-2 py-3 text-sm text-muted-foreground">
        <MessageSquare className="size-4" /> {empty}
      </p>
    )
  }
  return (
    <nav aria-label="Chat history" className="space-y-4">
      {byPeriod(runs).map((group) => (
        <section key={group.label} className="space-y-1">
          <h3 className="px-2 font-sans text-xs font-medium text-muted-foreground">{group.label}</h3>
          <ul>
            {group.runs.map((run) => {
              const active = ACTIVE.includes(run.status)
              const advisor = advisors?.find((a) => a.name === run.skill)
              return (
                <li key={run.id} className="group/chat relative">
                  <Link
                    to={chatHref(run)}
                    onClick={onNavigate}
                    aria-current={run.id === current ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2 rounded-lg py-1.5 pr-8 pl-2 text-sm transition-colors hover:bg-accent",
                      run.id === current && "bg-accent font-medium"
                    )}
                  >
                    {advisor && <AdvisorIcon name={advisor.name} group={advisor.group} className="size-5" />}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{chatTitle(run)}</span>
                      {advisors && (
                        <span className="block truncate text-xs font-normal text-muted-foreground">
                          {advisorName(run.skill)}
                        </span>
                      )}
                    </span>
                    {active && <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" aria-label="Answering" />}
                  </Link>
                  {!active && (
                    <button
                      type="button"
                      onClick={() => setDoomed(run)}
                      aria-label={`Delete chat: ${chatTitle(run)}`}
                      title="Delete chat"
                      className="absolute top-1/2 right-1.5 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity outline-none group-hover/chat:opacity-100 hover:bg-background hover:text-destructive-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
      <ConfirmDialog
        open={doomed !== null}
        onOpenChange={(open) => !open && setDoomed(null)}
        title="Delete this chat?"
        description={doomed ? `“${chatTitle(doomed)}”` : undefined}
        rollback="This cannot be undone. Reports it saved and decisions it recorded are kept."
        confirm="Delete chat"
        onConfirm={async () => {
          if (!doomed) return
          await remove(doomed.id)
          onDeleted(doomed.id)
        }}
      />
    </nav>
  )
}
