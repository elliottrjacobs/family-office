import { status } from "@/api/office"
import { useApi } from "@/api/use-api"

export function App() {
  const { data, error } = useApi("status", status, 5000)
  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl">Family Office</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {error ? error.message : data ? `fo ${data.version}, ${data.mode} mode` : "Loading"}
      </p>
    </main>
  )
}
