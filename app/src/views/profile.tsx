import { Check, Terminal } from "lucide-react"

import { type Level, levels, profile, profileFiles, type ProfileFile } from "@/api/office"
import { useApi } from "@/api/use-api"
import { useAppData } from "@/app-data"
import { AdvisorIcon, advisorName } from "@/components/advisor-icon"
import { ErrorNotice, Loading, Page, PageTitle, SectionTitle } from "@/components/page"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { percent, titleCase } from "@/lib/format"
import { Markdown } from "@/lib/markdown"

const LEVELS: Level[] = ["none", "household", "full"]
const LABELS: Record<string, string> = {
  household: "Household",
  ips: "Investment policy",
  goals: "Goals",
  tax: "Tax",
  accounts: "Account registry",
  categories: "Categories",
  universes: "Universes",
}

function LevelCards() {
  const { registry } = useAppData()
  const table = useApi("levels", levels)
  if (table.loading) return <Loading rows={1} />
  if (table.error) return <ErrorNotice error={table.error} retry={table.reload} />
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {LEVELS.map((level) => {
        const info = table.data![level]
        const advisors = (registry?.skills ?? []).filter((a) => a.default_context === level)
        return (
          <section key={level} className="flex flex-col rounded-xl border bg-card p-4">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-lg">{titleCase(level)}</h3>
              <span className="text-xs text-muted-foreground">{info.summary}</span>
            </div>
            <ul className="mt-3 flex-1 space-y-1.5 text-sm">
              {info.reads.map((line) => (
                <li key={line} className="flex gap-2">
                  <Check className="mt-0.5 size-3.5 shrink-0 text-success-foreground" />
                  {line}
                </li>
              ))}
            </ul>
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer text-muted-foreground">
                {info.files.length} files
              </summary>
              <ul className="mt-2 flex flex-wrap gap-1">
                {info.files.map((file) => (
                  <li key={file}>
                    <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{file}</code>
                  </li>
                ))}
              </ul>
            </details>
            <div className="mt-3 border-t pt-3">
              <p className="mb-2 text-xs text-muted-foreground">
                Default for {advisors.length} {advisors.length === 1 ? "advisor" : "advisors"}
              </p>
              <div className="flex flex-wrap gap-1">
                {advisors.map((a) => (
                  <Tooltip key={a.name}>
                    <TooltipTrigger render={<span tabIndex={0} />}>
                      <AdvisorIcon name={a.name} group={a.group} />
                    </TooltipTrigger>
                    <TooltipContent>{advisorName(a.name)}</TooltipContent>
                  </Tooltip>
                ))}
              </div>
            </div>
          </section>
        )
      })}
    </div>
  )
}

interface Band {
  name: string
  min: number
  max: number
}

function Structured({ file }: { file: ProfileFile }) {
  const data = file.data as Record<string, unknown> | null
  if (file.name === "household") return <Markdown text={file.text} className="text-sm" />
  if (file.name === "ips" && data) {
    const bands = (data.bands as Band[]) ?? []
    const classes = Object.entries((data.classifications as Record<string, string>) ?? {})
    return (
      <div className="space-y-4">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Band</TableHead>
              <TableHead className="text-right">Minimum</TableHead>
              <TableHead className="text-right">Maximum</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {bands.map((band) => (
              <TableRow key={band.name}>
                <TableCell>{band.name}</TableCell>
                <TableCell className="text-right font-mono text-xs">{percent(band.min, 0)}</TableCell>
                <TableCell className="text-right font-mono text-xs">{percent(band.max, 0)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {((data.prohibitions as string[]) ?? []).length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Prohibitions</p>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {(data.prohibitions as string[]).map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        )}
        {classes.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Classifications</p>
            <div className="flex flex-wrap gap-1.5">
              {classes.map(([symbol, band]) => (
                <Badge key={symbol} variant="outline" className="font-mono">
                  {symbol} → {band}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }
  return (
    <pre className="overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs leading-relaxed">
      {file.text}
    </pre>
  )
}

function FilePanel({ name }: { name: string }) {
  const file = useApi(`profile:${name}`, () => profile(name), 60_000)
  if (file.loading) return <Loading rows={2} />
  if (file.error) return <ErrorNotice error={file.error} retry={file.reload} />
  return (
    <section className="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg">{LABELS[name] ?? titleCase(name)}</h3>
        <code className="font-mono text-xs text-muted-foreground">{file.data!.file}</code>
      </div>
      {file.data!.error && (
        <p role="alert" className="rounded-lg bg-destructive/5 p-2 text-sm text-destructive-foreground">
          {file.data!.error}
        </p>
      )}
      <Structured file={file.data!} />
    </section>
  )
}

export function Profile() {
  const files = useApi("profile-files", profileFiles)
  return (
    <Page>
      <PageTitle
        title="What your advisors read"
        description="These files describe the household. Advisors read them at the context level each one is set to; only the onboard skill changes them, from your answers in a terminal."
      />
      <LevelCards />
      <SectionTitle
        aside={
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Terminal className="size-3.5" /> Edit with the onboard skill
          </span>
        }
      >
        Authored files
      </SectionTitle>
      {files.loading ? (
        <Loading rows={1} />
      ) : files.error ? (
        <ErrorNotice error={files.error} retry={files.reload} />
      ) : (
        <Tabs defaultValue="household">
          <TabsList className="mb-3 max-w-full overflow-x-auto [scrollbar-width:none]" variant="line">
            {files.data!.map((f) => (
              <TabsTrigger key={f.name} value={f.name}>
                {LABELS[f.name] ?? titleCase(f.name)}
              </TabsTrigger>
            ))}
          </TabsList>
          {files.data!.map((f) => (
            <TabsContent key={f.name} value={f.name}>
              <FilePanel name={f.name} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </Page>
  )
}
