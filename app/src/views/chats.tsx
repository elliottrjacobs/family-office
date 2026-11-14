import { runs } from "@/api/runs"
import { useApi } from "@/api/use-api"
import { useAppData } from "@/app-data"
import { ChatHistory } from "@/components/chat-history"
import { ErrorNotice, Loading, Page, PageTitle } from "@/components/page"

/** Every conversation, with every advisor, newest first. */
export function Chats() {
  const { registry, status } = useAppData()
  const history = useApi(status?.chat ? "runs" : "runs-off", () => (status?.chat ? runs() : Promise.resolve([])), 10_000)
  return (
    <Page className="max-w-3xl">
      <PageTitle title="Chats" description="Every conversation with your advisors, newest first." />
      {history.error && !history.data ? (
        <ErrorNotice error={history.error} retry={history.reload} />
      ) : history.loading ? (
        <Loading />
      ) : (
        <ChatHistory
          runs={history.data ?? []}
          advisors={registry?.skills ?? []}
          onDeleted={history.reload}
          empty="No chats yet. Open an advisor and ask it something."
        />
      )}
    </Page>
  )
}
