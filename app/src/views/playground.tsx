// The avatar playground (U21) at /playground/robots: every default at four sizes, every
// state, preset combinations, the live editor and both customize UIs. It renders with no
// office and makes no API calls. `?shot=<section id>&theme=light|dark` renders one section
// without chrome for scripts/screenshot-robots.mjs.

import * as React from "react"
import { Check, Copy } from "lucide-react"
import { cn } from "cn"

import type { Advisor } from "@/api/office"
import { OfflineAppData } from "@/app-data"
import {
  ADVISOR_IDS,
  ADVISORS,
  type AdvisorId,
  type Appearance,
  defaultAppearance,
  isAdvisorId,
  parseAppearance,
  type RobotState,
  serializeAppearance,
  STATES,
} from "@/avatars/appearance"
import { Robot } from "@/avatars/Robot"
import { saveAppearance, useAppearance } from "@/avatars/store"
import { STATE_LABELS } from "@/components/advisor-avatar"
import { AdvisorInspector } from "@/components/advisor-inspector"
import { AppearanceEditor } from "@/components/appearance-editor"
import { AppearanceSheet } from "@/components/appearance-sheet"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useLocation } from "@/lib/router"

export const SECTIONS = [
  { id: "defaults", title: "Defaults" },
  { id: "states", title: "States" },
  { id: "combinations", title: "Combinations" },
  { id: "editor", title: "Editor" },
  { id: "customize", title: "Customize UIs" },
] as const
type SectionId = (typeof SECTIONS)[number]["id"]
type Theme = "light" | "dark"

export const SIZES = [24, 34, 64, 160] as const

/** Six named looks that exercise the options together. */
export const COMBINATIONS: { name: string; advisor: AdvisorId; look: Partial<Appearance> }[] = [
  {
    name: "Hexagon, no antenna, brass, amber",
    advisor: "cio",
    look: { shape: "hexagon", antenna: "none", trim: "brass", screen: "amber" },
  },
  {
    name: "Capsule, twin antennas, copper, mint",
    advisor: "macro",
    look: { shape: "capsule", antenna: "twin", trim: "copper", screen: "mint", eyes: "dot", accessory: false },
  },
  {
    name: "Circle, matte, black trim, white screen",
    advisor: "research",
    look: { shape: "circle", finish: "matte", trim: "black", screen: "white", eyes: "ring" },
  },
  {
    name: "Wide, flag, silver, custom pink",
    advisor: "planner",
    look: { shape: "wide", antenna: "flag", trim: "silver", shell: "#F27BB5", eyes: "bar" },
  },
  {
    name: "Dome, periscope, steel, tinted on Graphite",
    advisor: "scout",
    look: { shape: "dome", antenna: "periscope", trim: "steel", screen: "tinted", shell: "#2C2F36", eyes: "square" },
  },
  {
    name: "Rocket, ball, custom teal trim, custom glow",
    advisor: "ventures",
    look: { shape: "rocket", antenna: "ball", trim: "#2BB5A6", screen: "#B8F1FF", shell: "#5B6B7F" },
  },
]

// A synthetic CIO for the inspector: fixed text, no registry and no preview call.
const SAMPLE_CIO: Advisor = {
  name: "cio",
  description: "Whole-portfolio decisions against the policy statement: drift, rebalancing and where new money goes.",
  group: "household",
  tier: "strong",
  default_context: "household",
  allowed_context: ["none", "household", "full"],
  invocation: "implicit",
  args: "",
  deep: false,
  commands: ["allocation", "drift"],
  report_kind: "cio",
}
const SAMPLE_READS = ["Household brief, about 2,400 tokens", "2 standing corrections", "3 open decisions"]

// Panels paint fixed colours so a light panel stays light under a dark app theme.
const PANEL: Record<Theme, string> = {
  light: "bg-white text-neutral-500 ring-1 ring-black/5",
  dark: "bg-[#111] text-neutral-400 ring-1 ring-white/10",
}

function Panel({ theme, className, children }: { theme: Theme; className?: string; children: React.ReactNode }) {
  return (
    <div data-panel={theme} className={cn("rounded-2xl p-6", PANEL[theme], theme === "dark" && "dark", className)}>
      {children}
    </div>
  )
}

function Caption({ children }: { children: React.ReactNode }) {
  return <span className="text-center text-xs leading-tight">{children}</span>
}

function AdvisorSelect({ value, onChange, label }: { value: AdvisorId; onChange: (id: AdvisorId) => void; label: string }) {
  const items = ADVISOR_IDS.map((id) => ({ value: id, label: ADVISORS[id].name }))
  return (
    <Select value={value} onValueChange={(next) => isAdvisorId(next) && onChange(next)} items={items}>
      <SelectTrigger aria-label={label} className="w-44">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function Defaults({ themes }: { themes: Theme[] }) {
  return (
    <div className="flex flex-col gap-6">
      {themes.map((theme) => (
        <Panel key={theme} theme={theme} className="w-[1240px] max-w-none space-y-6">
          {SIZES.map((size) => (
            <div key={size} className="space-y-2" data-size={size}>
              <p className="font-mono text-[11px]">{size} px</p>
              <div className="flex flex-wrap items-start gap-3">
                {ADVISOR_IDS.map((id) =>
                  size === 160 ? (
                    <div key={id} className="flex w-[160px] flex-col items-center gap-1">
                      <Robot advisor={id} size={size} appearance={defaultAppearance(id)} />
                      <Caption>{ADVISORS[id].name}</Caption>
                    </div>
                  ) : (
                    <Robot key={id} advisor={id} size={size} appearance={defaultAppearance(id)} />
                  )
                )}
              </div>
            </div>
          ))}
        </Panel>
      ))}
    </div>
  )
}

function States({ themes, initial }: { themes: Theme[]; initial: AdvisorId }) {
  const [advisor, setAdvisor] = React.useState<AdvisorId>(initial)
  return (
    <div className="space-y-4">
      <div data-chrome className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">Advisor</span>
        <AdvisorSelect value={advisor} onChange={setAdvisor} label="Advisor for the states" />
      </div>
      {themes.map((theme) => (
        <Panel key={theme} theme={theme} className="w-fit">
          <div className="grid grid-cols-4 gap-x-6 gap-y-4">
            {STATES.map((state: RobotState) => (
              <div key={state} className="flex w-[120px] flex-col items-center gap-1" data-state-cell={state}>
                <Robot
                  advisor={advisor}
                  size={120}
                  state={state}
                  level={state === "speaking" ? 0.6 : 0}
                  live
                />
                <Caption>{STATE_LABELS[state]}</Caption>
              </div>
            ))}
          </div>
        </Panel>
      ))}
    </div>
  )
}

function Combinations({ themes }: { themes: Theme[] }) {
  return (
    <div className="flex flex-col gap-6">
      {themes.map((theme) => (
        <Panel key={theme} theme={theme} className="w-fit">
          <div className="grid grid-cols-3 gap-x-8 gap-y-5">
            {COMBINATIONS.map(({ name, advisor, look }) => (
              <div key={name} className="flex w-[180px] flex-col items-center gap-1">
                <Robot advisor={advisor} size={120} appearance={{ ...defaultAppearance(advisor), ...look }} />
                <Caption>{name}</Caption>
                <span className="text-[10px] opacity-70">{ADVISORS[advisor].name}</span>
              </div>
            ))}
          </div>
        </Panel>
      ))}
    </div>
  )
}

function Editor() {
  const [advisor, setAdvisor] = React.useState<AdvisorId>("cio")
  const look = useAppearance(advisor)
  const json = JSON.stringify(JSON.parse(serializeAppearance(look)), null, 2)
  const [draft, setDraft] = React.useState<string | null>(null)
  const [note, setNote] = React.useState<string | null>(null)
  const [copied, setCopied] = React.useState(false)

  const apply = (text: string) => {
    let value: unknown
    try {
      value = JSON.parse(text)
    } catch {
      setNote("That is not JSON.")
      return
    }
    const parsed = parseAppearance(value, advisor)
    saveAppearance(advisor, parsed)
    setDraft(null)
    setNote("Applied. Unknown or invalid fields fall back to the default.")
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setNote("The browser refused the clipboard; copy from the text area.")
    }
  }

  return (
    <div className="grid gap-6 md:grid-cols-[320px_minmax(0,1fr)]">
      <div className="space-y-4">
        <AdvisorSelect
          value={advisor}
          onChange={(next) => {
            setAdvisor(next)
            setDraft(null)
            setNote(null)
          }}
          label="Advisor to edit"
        />
        <AppearanceEditor key={advisor} advisorId={advisor} />
      </div>
      <div className="min-w-0 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="playground-json" className="text-xs font-semibold">
            Appearance JSON
          </label>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={copy}>
              {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy JSON"}
            </Button>
            <Button size="sm" disabled={draft === null} onClick={() => draft !== null && apply(draft)}>
              Apply
            </Button>
          </div>
        </div>
        <textarea
          id="playground-json"
          value={draft ?? json}
          onChange={(event) => {
            setDraft(event.target.value)
            setNote(null)
          }}
          onPaste={(event) => {
            const text = event.clipboardData.getData("text")
            if (text) {
              event.preventDefault()
              apply(text)
            }
          }}
          spellCheck={false}
          rows={14}
          className="w-full rounded-lg border bg-background p-3 font-mono text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {note ?? "Paste a config to apply it, or edit and press Apply. It saves to this browser only."}
        </p>
      </div>
    </div>
  )
}

function PhoneFrame() {
  const [frame, setFrame] = React.useState<HTMLDivElement | null>(null)
  return (
    <div
      ref={setFrame}
      data-phone-frame
      // The transform makes the frame the containing block of the sheet's fixed layers.
      className="relative h-[760px] w-[375px] shrink-0 overflow-hidden rounded-[2.5rem] border-[6px] border-neutral-900 bg-background [transform:translateZ(0)]"
    >
      <div className="flex h-12 items-center justify-between border-b px-4 text-sm">
        <span className="font-medium">CIO</span>
        <span className="text-xs text-muted-foreground">Tap the robot</span>
      </div>
      <div className="flex justify-center pt-6">
        {frame && (
          <AppearanceSheet advisorId="cio" defaultOpen modal={false} container={frame} className="rounded-full">
            <Robot advisor="cio" size={64} />
          </AppearanceSheet>
        )}
      </div>
    </div>
  )
}

function Customize() {
  return (
    <div className="flex flex-wrap items-start gap-8">
      <div className="space-y-2">
        <p data-chrome className="text-xs text-muted-foreground">Mac inspector, 320 px</p>
        <div data-inspector-column className="w-[320px] rounded-2xl border bg-background p-4">
          <AdvisorInspector advisor={SAMPLE_CIO} state={{ state: "speaking", level: 0.6 }} reads={SAMPLE_READS} />
        </div>
      </div>
      <div className="space-y-2">
        <p data-chrome className="text-xs text-muted-foreground">Phone sheet, 375 px</p>
        <PhoneFrame />
      </div>
    </div>
  )
}

function SectionBody({ id, themes, advisor }: { id: SectionId; themes: Theme[]; advisor: AdvisorId }) {
  if (id === "defaults") return <Defaults themes={["light", "dark"]} />
  if (id === "states") return <States themes={themes} initial={advisor} />
  if (id === "combinations") return <Combinations themes={themes} />
  if (id === "editor") return <Editor />
  return <Customize />
}

/** Marks the section ready once fonts have loaded and a frame has painted. */
function useReady() {
  const [ready, setReady] = React.useState(false)
  React.useEffect(() => {
    let live = true
    const fonts = document.fonts?.ready ?? Promise.resolve()
    fonts.then(() => {
      requestAnimationFrame(() => live && setReady(true))
    })
    return () => {
      live = false
    }
  }, [])
  return ready
}

function Shot({ id, theme, advisor }: { id: SectionId; theme: Theme; advisor: AdvisorId }) {
  const ready = useReady()
  return (
    <div
      className={cn("min-h-svh p-6 [&_[data-chrome]]:hidden", theme === "dark" ? "dark bg-[#111] text-foreground" : "bg-white text-foreground")}
      style={{ colorScheme: theme }}
    >
      <section id={id} data-shot={id} data-ready={ready ? "true" : undefined} className="w-fit">
        <SectionBody id={id} themes={[theme]} advisor={advisor} />
      </section>
    </div>
  )
}

export function Playground() {
  const { query } = useLocation()
  const shot = SECTIONS.find((section) => section.id === query.get("shot"))?.id
  const theme: Theme = query.get("theme") === "dark" ? "dark" : "light"
  const requested = query.get("advisor")
  const advisor = isAdvisorId(requested) ? requested : "cio"

  return (
    <OfflineAppData>
      {shot ? (
        <Shot id={shot} theme={theme} advisor={advisor} />
      ) : (
        <div className="min-h-svh bg-background">
          <header className="sticky top-0 z-10 flex h-12 items-center gap-4 border-b bg-background/95 px-4 backdrop-blur">
            <span className="text-sm font-medium">Robot playground</span>
            <nav className="flex gap-3 overflow-x-auto text-xs text-muted-foreground">
              {SECTIONS.map((section) => (
                <a key={section.id} href={`#${section.id}`} className="whitespace-nowrap hover:text-foreground">
                  {section.title}
                </a>
              ))}
            </nav>
          </header>
          <main className="space-y-12 overflow-x-auto px-4 py-8 sm:px-8">
            {SECTIONS.map((section) => (
              <section key={section.id} id={section.id} className="scroll-mt-16 space-y-4">
                <h2 className="text-xl">{section.title}</h2>
                <SectionBody id={section.id} themes={["light", "dark"]} advisor={advisor} />
              </section>
            ))}
          </main>
        </div>
      )}
    </OfflineAppData>
  )
}
