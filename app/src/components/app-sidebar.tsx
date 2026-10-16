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
import { needsVerdict, useAppData } from "@/app-data"
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
                          <AdvisorIcon name={advisor.name} group={advisor.group} className="size-5" />
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
