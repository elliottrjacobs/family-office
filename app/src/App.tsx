import { LogIn, Unplug } from "lucide-react"

import { AppDataProvider, useAppData } from "@/app-data"
import { AppSidebar } from "@/components/app-sidebar"
import { Empty, Page } from "@/components/page"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { advisorName } from "@/components/advisor-icon"
import { moment } from "@/lib/format"
import { Link, useLocation } from "@/lib/router"
import { AdvisorPage } from "@/views/advisor"
import { Decisions } from "@/views/decisions"
import { Finances } from "@/views/finances"
import { Home } from "@/views/home"
import { OnboardingPage } from "@/views/onboarding"
import { Profile } from "@/views/profile"
import { ReportReader, Reports } from "@/views/reports"

function route(path: string) {
  if (path === "/") return { title: "Home", view: <Home /> }
  if (path === "/finances") return { title: "Finances", view: <Finances /> }
  if (path === "/reports") return { title: "Reports", view: <Reports /> }
  if (path === "/reports/view") return { title: "Report", view: <ReportReader /> }
  if (path === "/decisions") return { title: "Decisions", view: <Decisions /> }
  if (path === "/profile") return { title: "Profile", view: <Profile /> }
  const advisor = path.match(/^\/advisors\/([a-z0-9-]+)$/)
  if (advisor) return { title: advisorName(advisor[1]), view: <AdvisorPage name={advisor[1]} /> }
  return {
    title: "Not found",
    view: (
      <Page>
        <Empty icon={Unplug} title="Nothing here">
          <Link to="/" className="underline underline-offset-4">
            Back to Home
          </Link>
        </Empty>
      </Page>
    ),
  }
}

function Notice({ icon: Icon, title, children }: { icon: typeof LogIn; title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-sidebar px-4">
      <div className="w-full max-w-md space-y-3 rounded-2xl border bg-background p-6 text-center shadow-sm">
        <Icon className="mx-auto size-6 text-muted-foreground" />
        <h1 className="text-xl">{title}</h1>
        <div className="text-sm text-muted-foreground">{children}</div>
      </div>
    </div>
  )
}

function Shell() {
  const { status, statusError, onboarding, connected } = useAppData()
  const { path } = useLocation()

  if (statusError?.signedOut) {
    return (
      <Notice icon={LogIn} title="Open the link fo serve printed">
        This page needs the link from the terminal running fo serve. Each start issues a new
        one; press Enter there to print it again.
      </Notice>
    )
  }
  if (statusError && !status) {
    return (
      <Notice icon={Unplug} title="fo serve is not running">
        Start it again with <code className="font-mono">fo serve</code> in a terminal, then open
        the link it prints.
      </Notice>
    )
  }
  if (!onboarding) {
    // Office views wait for the first onboarding answer so nothing asks for an office
    // that does not exist yet.
    return <div className="min-h-svh bg-sidebar" aria-busy="true" />
  }
  if (onboarding.state === "no_office" || onboarding.state === "uninitialized_path") {
    return <OnboardingPage data={onboarding} />
  }

  const { title, view } = route(path)
  const lastSync = status?.office?.last_sync
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 rounded-t-xl border-b bg-background/95 px-3 backdrop-blur">
          <SidebarTrigger />
          <Separator orientation="vertical" className="mr-1 data-vertical:h-4 data-vertical:self-center" />
          <span className="truncate text-sm font-medium">{title}</span>
          <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            {!connected && <Badge variant="destructive">Disconnected</Badge>}
            {status?.read_only && <Badge variant="outline">Read-only</Badge>}
            <span className="hidden sm:inline">
              {lastSync ? `Synced ${moment(lastSync.as_of)}` : "Not synced"}
            </span>
          </span>
        </header>
        {!connected && (
          <div role="status" className="border-b bg-destructive/5 px-4 py-2 text-sm text-destructive-foreground">
            Lost contact with fo serve. Figures on screen may be out of date until it is running again.
          </div>
        )}
        <div className="flex-1">{view}</div>
      </SidebarInset>
    </SidebarProvider>
  )
}

export function App() {
  return (
    <AppDataProvider>
      <Shell />
    </AppDataProvider>
  )
}
