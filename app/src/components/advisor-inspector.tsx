// The Mac advisor inspector from the Figma chat frame (U20): the live robot with its
// state, the advisor, its look, what it reads and where it writes.

import * as React from "react"
import { Check, FileText, Lock, Terminal } from "lucide-react"

import type { Advisor, Level } from "@/api/office"
import { levels } from "@/api/office"
import { preview } from "@/api/runs"
import { useApi } from "@/api/use-api"
import { advisorIdFor } from "@/avatars/appearance"
import { useAdvisorState, useLiveRun } from "@/components/advisor-avatar"
import { AppearanceControls, AppearancePreview } from "@/components/appearance-editor"
import { advisorName } from "@/components/advisor-icon"
import { Segmented } from "@/components/segmented"
import { day, titleCase } from "@/lib/format"

const INSPECTOR_KEY = "fo.advisor-inspector.v1"

/** Whether the inspector is shown, remembered in this browser; shown unless hidden before. */
export function useInspectorShown(): [boolean, (shown: boolean) => void] {
  const [shown, setShown] = React.useState(() => {
    try {
      return window.localStorage.getItem(INSPECTOR_KEY) !== "hidden"
    } catch {
      return true
    }
  })
  const update = React.useCallback((next: boolean) => {
    setShown(next)
    try {
      window.localStorage.setItem(INSPECTOR_KEY, next ? "shown" : "hidden")
    } catch {
      // Blocked storage only forgets the choice.
    }
  }, [])
  return [shown, update]
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-semibold text-foreground">{children}</h3>
}

function CheckList({ lines }: { lines: string[] }) {
  return (
    <ul className="space-y-1.5 text-[13px]">
      {lines.map((line) => (
        <li key={line} className="flex gap-2">
          <Check className="mt-0.5 size-3.5 shrink-0 text-success-foreground" />
          <span className="min-w-0">{line}</span>
        </li>
      ))}
    </ul>
  )
}

/**
 * What the advisor reads at a level: the brief counts from the same preview call the launch
 * panel makes when the subject is known, otherwise the level's description.
 */
function Reads({ advisor, subject, level }: { advisor: Advisor; subject: string | null; level: Level }) {
  const table = useApi("levels", levels)
  const loaded = useApi(`preview:${advisor.name}:${subject ?? "-"}:${level}`, () =>
    subject ? preview(advisor.name, subject, level) : Promise.resolve(undefined)
  )
  const brief = loaded.data?.brief.data
  const prior = loaded.data?.prior.data
  if (subject && brief) {
    const lines = [
      level === "none"
        ? "No household brief"
        : `${titleCase(brief.level)} brief, about ${brief.estimated_tokens} tokens`,
      `${brief.corrections.length} standing ${brief.corrections.length === 1 ? "correction" : "corrections"}`,
      `${brief.decisions.length} open ${brief.decisions.length === 1 ? "decision" : "decisions"}`,
    ]
    if (prior) lines.push(`Prior ${advisorName(advisor.name)} report, ${day(prior.frontmatter.date)}`)
    return <CheckList lines={lines} />
  }
  const reads = table.data?.[level]?.reads
  if (reads) return <CheckList lines={reads} />
  return <p className="text-xs text-muted-foreground">Loading…</p>
}

export function AdvisorInspector({ advisor }: { advisor: Advisor }) {
  const robot = advisorIdFor(advisor.name)
  const { state, level: amplitude } = useAdvisorState(robot)
  const live = useLiveRun(robot)
  const name = advisorName(advisor.name)
  const household = advisor.group === "household" || advisor.group === "routine"
  const subject = live?.run?.subject ?? (household ? "household" : null)
  const runLevel = live?.run?.level
  const [chosen, setChosen] = React.useState<Level | null>(null)
  const level = chosen ?? (runLevel && advisor.allowed_context.includes(runLevel) ? runLevel : advisor.default_context)

  return (
    <aside aria-label={`${name} inspector`} className="space-y-6 text-sm" data-inspector>
      {robot && <AppearancePreview advisorId={robot} state={state} level={amplitude} className="min-h-44" />}
      <div className="space-y-1">
        <h2 className="text-xl">{name}</h2>
        <p className="text-[13px] text-muted-foreground">{advisor.description}</p>
      </div>
      {robot && <AppearanceControls advisorId={robot} />}
      <section className="space-y-2.5">
        <Heading>What {name} reads</Heading>
        <Reads advisor={advisor} subject={subject} level={level} />
      </section>
      {advisor.allowed_context.length > 1 && (
        <section className="space-y-2">
          <Heading>Context level</Heading>
          <Segmented
            label="Context level"
            className="w-full [&>button]:flex-1"
            options={advisor.allowed_context.map((value) => ({ value, label: titleCase(value) }))}
            value={level}
            onChange={setChosen}
          />
          <p className="text-xs text-muted-foreground">Shows what each level reads. Pick the level when you start a conversation.</p>
        </section>
      )}
      <section className="space-y-2">
        <Heading>Writes to</Heading>
        <p className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <FileText className="size-3.5 shrink-0 text-success-foreground" />
          reports/{advisor.report_kind}/
        </p>
      </section>
      {advisor.commands.length > 0 && (
        <section className="space-y-2">
          <Heading>Commands</Heading>
          <ul className="space-y-1">
            {advisor.commands.map((command) => (
              <li key={command}>
                <code className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                  <Terminal className="size-3 shrink-0" />
                  fo {command} --json
                </code>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="flex gap-1.5 border-t pt-4 text-xs text-muted-foreground">
        <Lock className="mt-0.5 size-3 shrink-0" />
        <span>Advisors read your office on this Mac. Nothing here can trade or move money.</span>
      </p>
    </aside>
  )
}
