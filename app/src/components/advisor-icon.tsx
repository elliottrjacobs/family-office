import {
  Activity,
  BadgePercent,
  Calculator,
  Castle,
  ClipboardCheck,
  CloudSun,
  Compass,
  Globe,
  House,
  Landmark,
  Layers,
  Lightbulb,
  ListChecks,
  type LucideIcon,
  Microscope,
  Newspaper,
  NotebookPen,
  Receipt,
  Rocket,
  Route,
  Search,
  ShieldAlert,
  Sparkles,
  Store,
  Telescope,
  TrendingUp,
  UserPlus,
  UserSearch,
  Wallet,
  Waves,
} from "lucide-react"
import { cn } from "cn"

import type { Group } from "@/api/office"

const ICONS: Record<string, LucideIcon> = {
  cio: Compass,
  cfo: Wallet,
  plan: Route,
  tax: Receipt,
  research: Microscope,
  diligence: UserSearch,
  scout: Telescope,
  macro: Globe,
  options: Layers,
  technicals: Activity,
  risk: ShieldAlert,
  realestate: House,
  ventures: Rocket,
  estate: Landmark,
  journal: NotebookPen,
  briefing: Newspaper,
  review: ClipboardCheck,
  onboard: UserPlus,
  eli5: Lightbulb,
  "lead-edge-eight": ListChecks,
  piotroski: Calculator,
  greenblatt: BadgePercent,
  compounder: TrendingUp,
  lynch: Store,
  fisher: Search,
  powers: Castle,
  marks: Waves,
  "all-weather": CloudSun,
}

export const GROUP_LABELS: Record<Group, string> = {
  household: "Household",
  research: "Research",
  specialists: "Specialists",
  routine: "Routine",
  playbooks: "Playbooks",
}
export const GROUP_ORDER: Group[] = ["household", "research", "specialists", "routine", "playbooks"]

// Order within each sidebar group, as the README lists them; new skills sort after these.
const ADVISOR_ORDER = [
  "cio", "cfo", "plan", "tax",
  "research", "diligence", "scout", "macro",
  "options", "technicals", "risk", "realestate", "ventures", "estate",
  "journal", "briefing", "review", "onboard", "eli5",
  "lead-edge-eight", "piotroski", "greenblatt", "compounder", "lynch", "fisher", "powers", "marks", "all-weather",
]

export function byAdvisorOrder(a: { name: string }, b: { name: string }) {
  const rank = (name: string) => {
    const index = ADVISOR_ORDER.indexOf(name)
    return index === -1 ? ADVISOR_ORDER.length : index
  }
  return rank(a.name) - rank(b.name) || a.name.localeCompare(b.name)
}

const TINTS: Record<Group, string> = {
  household: "bg-success/12 text-success-foreground",
  research: "bg-info/12 text-info-foreground",
  specialists: "bg-warning/15 text-warning-foreground",
  routine: "bg-muted text-muted-foreground",
  playbooks: "bg-destructive/10 text-destructive-foreground",
}

/** Display names keep acronyms upper case and spell out the shorthand ones. */
const NAMES: Record<string, string> = {
  cio: "CIO",
  cfo: "CFO",
  plan: "Planner",
  realestate: "Real estate",
  eli5: "ELI5",
  "lead-edge-eight": "Lead Edge Eight",
  "all-weather": "All Weather",
}

export function advisorName(name: string) {
  return NAMES[name] ?? name[0].toUpperCase() + name.slice(1)
}

export function AdvisorIcon({
  name,
  group,
  className,
}: {
  name: string
  group: Group
  className?: string
}) {
  const Icon = ICONS[name] ?? Sparkles
  return (
    <span
      className={cn(
        "inline-flex size-6 shrink-0 items-center justify-center rounded-md",
        TINTS[group],
        className
      )}
    >
      <Icon className="size-3.5" aria-hidden />
    </span>
  )
}
