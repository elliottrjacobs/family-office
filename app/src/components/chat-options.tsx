/** What a new conversation starts with: context level, engine, model, effort, deep mode. */

import * as React from "react"
import { SlidersHorizontal } from "lucide-react"

import type { Advisor, Level } from "@/api/office"
import {
  type Effort,
  type EngineChoice,
  type EngineStatus,
  engineLabel,
  type ModelCatalog,
  models,
} from "@/api/runs"
import { useApi } from "@/api/use-api"
import { advisorName } from "@/components/advisor-icon"
import { Segmented } from "@/components/segmented"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { titleCase } from "@/lib/format"

const EFFORTS: Effort[] = ["low", "medium", "high", "xhigh", "max"]
const EFFORT_LABELS: Partial<Record<Effort, string>> = { xhigh: "Extra high" }
const OTHER = "__other__"
const STORAGE = "fo.launch.v1."

function remembered(advisor: string): EngineChoice | undefined {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(STORAGE + advisor) ?? "null") as EngineChoice | null
    if (value && typeof value.engine === "string" && typeof value.model === "string" && EFFORTS.includes(value.effort)) {
      return value
    }
  } catch {
    // Unreadable or blocked storage falls back to the office defaults.
  }
  return undefined
}

export function remember(advisor: string, choice: EngineChoice) {
  try {
    window.sessionStorage.setItem(STORAGE + advisor, JSON.stringify(choice))
  } catch {
    // The choice is a convenience; losing it is harmless.
  }
}

/** The office default for an engine, then the curated recommendation, then the first entry. */
function defaultsFor(engine: string, catalog: ModelCatalog | undefined, engines: EngineStatus[]): EngineChoice {
  const office = catalog?.defaults[engine] ?? engines.find((e) => e.name === engine)?.defaults
  const curated = catalog?.engines[engine]?.models ?? []
  const recommended = curated.find((m) => m.recommended) ?? curated[0]
  return { engine, model: office?.model ?? recommended?.id ?? "", effort: office?.effort ?? "high" }
}

export function initialChoice(
  advisor: string,
  catalog: ModelCatalog | undefined,
  engines: EngineStatus[],
  officeDefault: string | undefined
): EngineChoice | undefined {
  const usable = engines.filter((e) => e.usable).map((e) => e.name)
  if (!usable.length) return undefined
  const stored = remembered(advisor)
  if (stored && usable.includes(stored.engine)) return stored
  const preferred = catalog?.default ?? officeDefault
  return defaultsFor(preferred && usable.includes(preferred) ? preferred : usable[0], catalog, engines)
}

const SELECT =
  "h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"

/** A labelled control in the engine row. */
function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children}
    </div>
  )
}

/** Engine, model, and effort for this run; unusable engines show why and cannot be chosen. */
function EngineFields({
  choice,
  catalog,
  engines,
  onChange,
}: {
  choice: EngineChoice
  catalog: ModelCatalog | undefined
  engines: EngineStatus[]
  onChange: (choice: EngineChoice) => void
}) {
  const curated = catalog?.engines[choice.engine]?.models ?? []
  const listed = curated.some((m) => m.id === choice.model)
  const [other, setOther] = React.useState(!listed && choice.model !== "")
  const custom = other || (!listed && choice.model !== "")
  const efforts = catalog?.engines[choice.engine]?.efforts ?? EFFORTS
  const blocked = engines.filter((e) => !e.usable && e.message)
  return (
    <div className="space-y-3">
      {/* Three dropdowns of one height in one row, so the labels and controls line up. */}
      <div className="grid gap-3 sm:grid-cols-[1fr_1.4fr_1fr]">
        <Field id="run-engine" label="Engine">
          <select
            id="run-engine"
            value={choice.engine}
            onChange={(event) => {
              setOther(false)
              onChange(defaultsFor(event.target.value, catalog, engines))
            }}
            className={SELECT}
          >
            {engines.map((e) => (
              <option key={e.name} value={e.name} disabled={!e.usable}>
                {catalog?.engines[e.name]?.label ?? engineLabel(e.name)}
                {e.usable ? "" : " (unavailable)"}
              </option>
            ))}
          </select>
        </Field>
        <Field id="run-model" label="Model">
          <select
            id="run-model"
            value={custom ? OTHER : choice.model}
            onChange={(event) => {
              const value = event.target.value
              if (value === OTHER) {
                setOther(true)
                onChange({ ...choice, model: "" })
              } else {
                setOther(false)
                onChange({ ...choice, model: value })
              }
            }}
            className={SELECT}
          >
            {curated.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
                {m.recommended ? " (recommended)" : ""}
              </option>
            ))}
            <option value={OTHER}>Other…</option>
          </select>
        </Field>
        <Field id="run-effort" label="Effort">
          <select
            id="run-effort"
            value={choice.effort}
            onChange={(event) => onChange({ ...choice, effort: event.target.value as Effort })}
            className={SELECT}
          >
            {efforts.map((value) => (
              <option key={value} value={value}>
                {EFFORT_LABELS[value] ?? titleCase(value)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {custom && (
        <Input
          aria-label="Model id"
          value={choice.model}
          onChange={(event) => onChange({ ...choice, model: event.target.value.trim() })}
          placeholder="Model id, as the engine names it"
          autoComplete="off"
          spellCheck={false}
        />
      )}
      {blocked.map((e) => (
        <p key={e.name} className="text-xs text-muted-foreground">
          {catalog?.engines[e.name]?.label ?? engineLabel(e.name)} is unavailable: {e.message}
        </p>
      ))}
    </div>
  )
}

/** What each context level means, in the words the picker shows. */
export const LEVEL_LABELS: Record<Level, { label: string; detail: string }> = {
  none: { label: "No household data", detail: "General answers only; nothing from your accounts." },
  household: { label: "Household brief", detail: "Holdings, policy, and cash, in a short brief." },
  full: { label: "Full profile", detail: "Everything: members, goals, tax notes, and cash flow." },
}

export interface ChatSettings {
  level: Level
  deep: boolean
  choice: EngineChoice | undefined
}

/** The settings a new conversation starts from, remembered per advisor for this session. */
export function useChatSettings(
  advisor: Advisor,
  engines: EngineStatus[],
  officeDefault: string | undefined
): { settings: ChatSettings; catalog: ModelCatalog | undefined; update: (next: Partial<ChatSettings>) => void } {
  const catalog = useApi("models", models)
  // Null until the user picks something; until then the office defaults apply.
  const [picked, setPicked] = React.useState<{ advisor: string; value: Partial<ChatSettings> }>({
    advisor: advisor.name,
    value: {},
  })
  const mine = picked.advisor === advisor.name ? picked.value : {}
  const settings: ChatSettings = {
    level: mine.level ?? advisor.default_context,
    deep: mine.deep ?? false,
    choice: mine.choice ?? initialChoice(advisor.name, catalog.data, engines, officeDefault),
  }
  const update = (next: Partial<ChatSettings>) => {
    if (next.choice) remember(advisor.name, next.choice)
    setPicked({ advisor: advisor.name, value: { ...mine, ...next } })
  }
  return { settings, catalog: catalog.data, update }
}

/** The model's name as the catalog lists it, else its id. */
export function modelLabel(choice: EngineChoice | undefined, catalog: ModelCatalog | undefined) {
  if (!choice) return "Model"
  const listed = catalog?.engines[choice.engine]?.models.find((m) => m.id === choice.model)
  return listed?.label ?? (choice.model || "Model")
}

/** Context, model, effort, and deep mode for a conversation that has not started yet. */
export function ChatOptions({
  advisor,
  settings,
  catalog,
  engines,
  deepAvailable,
  onChange,
}: {
  advisor: Advisor
  settings: ChatSettings
  catalog: ModelCatalog | undefined
  engines: EngineStatus[]
  deepAvailable: boolean
  onChange: (next: Partial<ChatSettings>) => void
}) {
  const [open, setOpen] = React.useState(false)
  const canDeep = advisor.deep && deepAvailable
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="max-w-[16rem] text-muted-foreground"
        aria-label="Conversation options"
        onClick={() => setOpen(true)}
      >
        <SlidersHorizontal />
        <span className="truncate">
          {LEVEL_LABELS[settings.level].label} · {modelLabel(settings.choice, catalog)}
        </span>
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Options for this chat</DialogTitle>
            <DialogDescription>
              These apply to a new conversation with {advisorName(advisor.name)} and stay with it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            {advisor.allowed_context.length > 1 && (
              <div className="space-y-1.5">
                <p className="text-sm font-medium">What {advisorName(advisor.name)} may read</p>
                <Segmented
                  label="Context level"
                  options={advisor.allowed_context.map((value) => ({
                    value,
                    label: LEVEL_LABELS[value].label,
                  }))}
                  value={settings.level}
                  onChange={(level) => onChange({ level })}
                />
                <p className="text-xs text-muted-foreground">{LEVEL_LABELS[settings.level].detail}</p>
              </div>
            )}
            {/* The fields wait for the curated list so an office model shows as listed or as Other. */}
            {settings.choice && catalog && (
              <EngineFields
                key={settings.choice.engine}
                choice={settings.choice}
                catalog={catalog}
                engines={engines}
                onChange={(choice) => onChange({ choice })}
              />
            )}
            {canDeep && (
              <label className="flex items-center gap-3 text-sm">
                <Switch
                  checked={settings.deep}
                  onCheckedChange={(deep) => onChange({ deep })}
                  aria-label="Deep mode"
                />
                <span>
                  Deep mode
                  <span className="block text-xs text-muted-foreground">
                    Five analysts gather evidence first; slower and costlier.
                  </span>
                </span>
              </label>
            )}
          </div>
          <DialogFooter>
            <Button type="button" onClick={() => setOpen(false)}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
