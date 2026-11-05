import * as React from "react"
import {
  ChartPie,
  ChevronDown,
  FileText,
  House,
  IdCard,
  Monitor,
  Moon,
  Scale,
  Search,
  Sun,
} from "lucide-react"

import type { Advisor } from "@/api/office"
import { ACTIVE, type Run, runs } from "@/api/runs"
import { useApi } from "@/api/use-api"
import { needsVerdict, useAppData } from "@/app-data"
import { type AdvisorId, advisorIdFor } from "@/avatars/appearance"
import { Robot } from "@/avatars/Robot"
import { useAdvisorState, useLiveRun } from "@/components/advisor-avatar"
import {
  AdvisorIcon,
  advisorName,
  byAdvisorOrder,
  GROUP_LABELS,
  GROUP_ORDER,
} from "@/components/advisor-icon"
import { useTheme } from "@/components/theme-provider"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInput,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar"
import { moment } from "@/lib/format"
import { Link, useLocation } from "@/lib/router"

const NAV = [
  { to: "/", label: "Home", icon: House },
  { to: "/finances", label: "Finances", icon: ChartPie },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/decisions", label: "Decisions", icon: Scale },
  { to: "/profile", label: "Profile", icon: IdCard },
]

function active(path: string, to: string) {
  return to === "/" ? path === "/" : path === to || path.startsWith(to + "/")
}

function NavLink({ to, onClick, ...props }: Omit<React.ComponentProps<"a">, "href"> & { to: string }) {
  const { isMobile, setOpenMobile } = useSidebar()
  return (
    <Link
      to={to}
      {...props}
      onClick={(event) => {
        onClick?.(event)
        if (isMobile) setOpenMobile(false)
      }}
    />
  )
}

const ROW_ROBOT = 24
// Tailwind's important suffix beats the menu button's `[&_svg]:size-4`.
const ROW_ROBOT_CLASS = "size-6! shrink-0 -my-1"

/** The live robot of an advisor with a conversation or run in progress. */
function LiveRowRobot({ advisor, run }: { advisor: AdvisorId; run: Run | undefined }) {
  const { state, level } = useAdvisorState(advisor, run)
  // Small robots animate only while the advisor is doing something.
  return <Robot advisor={advisor} size={ROW_ROBOT} state={state} level={level} live={state !== "idle"} className={ROW_ROBOT_CLASS} />
}

function RowAvatar({ advisor, active }: { advisor: Advisor; active: Run | undefined }) {
  const { connected } = useAppData()
  const id = advisorIdFor(advisor.name)
  const published = useLiveRun(id)
  if (!id) return <AdvisorIcon name={advisor.name} group={advisor.group} className="size-5" />
  if (published || active) return <LiveRowRobot advisor={id} run={active} />
  return <Robot advisor={id} size={ROW_ROBOT} state={connected ? "idle" : "sleeping"} className={ROW_ROBOT_CLASS} />
}

function ThemeSwitch() {
  const { theme, setTheme } = useTheme()
  const next = theme === "light" ? "dark" : theme === "dark" ? "system" : "light"
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
      aria-label={`Theme: ${theme}. Switch to ${next}.`}
      title={`Theme: ${theme}`}
    >
      <Icon className="size-4" />
    </button>
  )
}

export function AppSidebar() {
  const { path } = useLocation()
  const { status, registry, review } = useAppData()
  const [query, setQuery] = React.useState("")
  // Runs in progress, so the sidebar shows which advisor is working on any page.
  const history = useApi(status?.chat ? "runs" : "runs-off", () => (status?.chat ? runs() : Promise.resolve([])), 5_000)
  const working = new Map<string, Run>()
  for (const run of history.data ?? []) {
    if (ACTIVE.includes(run.status) && !working.has(run.skill)) working.set(run.skill, run)
  }
  const office = status?.office
  const verdicts = needsVerdict(review).length
  const folder = office?.office.split("/").filter(Boolean).pop() ?? "Family Office"
  const lastSync = office?.last_sync
  const advisors = (registry?.skills ?? []).filter((a) => {
    const q = query.trim().toLowerCase()
    return !q || a.name.includes(q) || advisorName(a.name).toLowerCase().includes(q) || a.description.toLowerCase().includes(q)
  })
  const groups = GROUP_ORDER.map((group) => ({
    group,
    advisors: advisors.filter((a) => a.group === group).sort(byAdvisorOrder),
  })).filter((g) => g.advisors.length)

  return (
    <Sidebar variant="inset" collapsible="offcanvas">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-1 py-1">
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary font-heading text-sm text-primary-foreground">
            {folder[0]?.toUpperCase() ?? "F"}
          </span>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-sm font-semibold">Family Office</p>
            <p className="truncate text-xs text-muted-foreground" title={office?.office}>
              {office ? folder : "No office open"}
            </p>
          </div>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <SidebarInput
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find an advisor"
            aria-label="Find an advisor"
            className="pl-7"
          />
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map(({ to, label, icon: Icon }) => (
                <SidebarMenuItem key={to}>
                  <SidebarMenuButton isActive={active(path, to)} render={<NavLink to={to} />}>
                    <Icon />
                    <span>{label}</span>
                  </SidebarMenuButton>
                  {to === "/decisions" && verdicts > 0 && <SidebarMenuBadge>{verdicts}</SidebarMenuBadge>}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        {groups.map(({ group, advisors }) => (
          <Collapsible key={group} defaultOpen className="group/collapsible">
            <SidebarGroup className="py-0">
              <SidebarGroupLabel
                render={<CollapsibleTrigger />}
                className="w-full justify-between hover:bg-sidebar-accent"
              >
                {GROUP_LABELS[group]}
                <ChevronDown className="transition-transform group-data-[closed]/collapsible:-rotate-90" />
              </SidebarGroupLabel>
              <CollapsibleContent>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {advisors.map((advisor: Advisor) => (
                      <SidebarMenuItem key={advisor.name}>
                        <SidebarMenuButton
                          isActive={path === `/advisors/${advisor.name}`}
                          render={<NavLink to={`/advisors/${advisor.name}`} />}
                        >
                          <RowAvatar advisor={advisor} active={working.get(advisor.name)} />
                          <span>{advisorName(advisor.name)}</span>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </CollapsibleContent>
            </SidebarGroup>
          </Collapsible>
        ))}
        {registry && !groups.length && (
          <p className="px-4 py-2 text-xs text-muted-foreground">No advisor matches “{query}”.</p>
        )}
      </SidebarContent>
      <SidebarFooter>
        <div className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs">
          <span
            className={
              lastSync?.status === "complete"
                ? "size-2 rounded-full bg-success"
                : "size-2 rounded-full bg-muted-foreground/40"
            }
            aria-hidden
          />
          <span className="min-w-0 flex-1 truncate text-muted-foreground">
            {lastSync ? `Synced ${moment(lastSync.as_of)}` : office ? "Never synced" : "No office"}
          </span>
          {status?.identity && (
            <Badge variant="outline" title="Tailnet login">
              {status.identity.login}
            </Badge>
          )}
          <ThemeSwitch />
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
