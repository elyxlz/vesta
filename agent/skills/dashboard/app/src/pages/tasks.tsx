import { useEffect, useState, useCallback, lazy, Suspense } from "react"
import { apiFetch } from "@/lib/parent-bridge"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { toast } from "sonner"
import {
  RefreshCwIcon,
  AlertTriangleIcon,
  CalendarClockIcon,
  CalendarIcon,
  InboxIcon,
  CheckCircle2Icon,
  RepeatIcon,
  ChevronDownIcon,
  BellIcon,
} from "lucide-react"

// The markdown renderer is only needed once a row is opened, so it loads as its own chunk
// instead of weighing down every page load.
const MarkdownNotes = lazy(() => import("@/components/markdown-notes"))

interface Task {
  id: string
  subject: string
  status: string
  priority: number
  due_date: string | null
  created_at: string
  completed_at: string | null
}

// Working notes are a markdown file, one per id, that the tasks and reminders services each
// return as `metadata_content` on their single-item endpoint. Both list endpoints leave it out on
// purpose (some files are tens of KB), so notes are fetched one row at a time, on first expand,
// and cached after that.
interface Notes {
  state: "loading" | "ready" | "error"
  content: string | null
}

type Service = "tasks" | "reminders"

// Both services answer at <service>/<service>/<id>, so one key covers rows from either list.
const noteKey = (service: Service, id: string) => `${service}:${id}`

interface Reminder {
  id: string
  message: string
  schedule: string
  next_run: string | null
  status: string
}

// A "cron" is a recurring reminder: its schedule is not a one-shot ("once at ...").
function isRecurring(r: Reminder): boolean {
  const s = (r.schedule || "").trim().toLowerCase()
  return !s.startsWith("once")
}

function relNext(next: string | null): string {
  if (!next) return ""
  const t = new Date(next).getTime()
  const now = Date.now()
  const diffH = (t - now) / 3600000
  const abs = new Date(next).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
  if (diffH < 1) return `${abs} · soon`
  if (diffH < 24) return `${abs} · in ${Math.round(diffH)}h`
  return `${abs} · in ${Math.round(diffH / 24)}d`
}

type GroupKey = "overdue" | "week" | "later" | "none"

const GROUPS: { key: GroupKey; label: string; icon: React.ReactNode; accent: string }[] = [
  { key: "overdue", label: "Overdue", icon: <AlertTriangleIcon className="size-3.5" />, accent: "text-red-400" },
  { key: "week", label: "This week", icon: <CalendarClockIcon className="size-3.5" />, accent: "text-amber-400" },
  { key: "later", label: "Later", icon: <CalendarIcon className="size-3.5" />, accent: "text-sky-400" },
  { key: "none", label: "No due date", icon: <InboxIcon className="size-3.5" />, accent: "text-muted-foreground" },
]

const DAY = 86400000

function classifyDue(due: string | null): GroupKey {
  if (!due) return "none"
  const t = new Date(due).getTime()
  const now = Date.now()
  if (t < now) return "overdue"
  if (t < now + 7 * DAY) return "week"
  return "later"
}

function relDue(due: string | null): { text: string; tone: string } {
  if (!due) return { text: "", tone: "text-muted-foreground" }
  const t = new Date(due).getTime()
  const now = Date.now()
  const diffDays = Math.round((t - now) / DAY)
  const abs = new Date(due).toLocaleDateString(undefined, { day: "numeric", month: "short" })
  if (diffDays < 0) {
    const d = Math.abs(diffDays)
    return { text: `${abs} · ${d}d overdue`, tone: "text-red-400" }
  }
  if (diffDays === 0) return { text: `${abs} · today`, tone: "text-amber-400" }
  if (diffDays === 1) return { text: `${abs} · tomorrow`, tone: "text-amber-400" }
  if (diffDays <= 7) return { text: `${abs} · in ${diffDays}d`, tone: "text-amber-300" }
  return { text: abs, tone: "text-muted-foreground" }
}

// Tasks CLI priority semantics: 1 = low, 2 = normal, 3 = high. High is the alarming colour.
const PRIORITY: Record<number, { label: string; cls: string } | undefined> = {
  3: { label: "high", cls: "bg-red-500/15 text-red-400 border-red-500/30" },
  2: { label: "med", cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
  1: { label: "low", cls: "bg-muted text-muted-foreground border-transparent" },
}

function ExpandToggle({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={open ? "Hide notes" : "Show notes"}
      aria-expanded={open}
      onClick={onClick}
      className="mt-0.5 shrink-0 cursor-pointer text-muted-foreground hover:text-foreground"
    >
      <ChevronDownIcon className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
    </button>
  )
}

// The open half of a row. It scrolls on its own, so a 30 KB file never pushes the list off screen,
// and a row with nothing written about it says so quietly instead of reading as a failure.
function NotesPanel({ notes, onRetry }: { notes: Notes | undefined; onRetry: () => void }) {
  return (
    <div className="max-h-80 overflow-y-auto border-t border-border/50 px-2.5 py-2">
      {!notes || notes.state === "loading" ? (
        <div className="space-y-1.5">
          <Skeleton className="h-3 w-1/3" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      ) : notes.state === "error" ? (
        <p className="text-xs text-muted-foreground">
          Couldn't read the notes.{" "}
          <button type="button" onClick={onRetry} className="cursor-pointer underline underline-offset-2">
            Try again
          </button>
        </p>
      ) : notes.content ? (
        <Suspense fallback={<Skeleton className="h-3 w-full" />}>
          <MarkdownNotes>{notes.content}</MarkdownNotes>
        </Suspense>
      ) : (
        <p className="text-xs text-muted-foreground italic">No notes yet.</p>
      )}
    </div>
  )
}

// Exported as a self-contained section so the Home page can embed the full tasks + reminders
// experience (tabs, grouping, notes, completion) below its agenda without rebuilding any of it.
export function TasksAndReminders() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [completing, setCompleting] = useState<Set<string>>(new Set())
  const [tab, setTab] = useState("tasks")
  // One row open at a time: the notes are long, so two open rows bury the page. The key carries
  // its service, so a task and a reminder can never collide.
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [notes, setNotes] = useState<Record<string, Notes>>({})

  const load = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) setRefreshing(true)
    // A refresh drops cached notes so an open row re-reads its file.
    if (isRefresh) setNotes({})
    try {
      const res = await apiFetch("tasks/tasks")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: Task[] = await res.json()
      setTasks(Array.isArray(data) ? data.filter((t) => t.status !== "done") : [])
      // Reminders (crons) come from the reminders skill's own service and are best-effort:
      // a failure here (skill inactive, daemon down) must not break tasks.
      try {
        const remRes = await apiFetch("reminders/reminders")
        if (remRes.ok) {
          const remData = await remRes.json()
          const list: Reminder[] = Array.isArray(remData) ? remData : (remData?.reminders ?? [])
          setReminders(list)
        }
      } catch {
        /* ignore reminder load errors */
      }
    } catch (e) {
      toast.error("Couldn't load tasks")
      console.error(e)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load(false)
  }, [load])

  const loadNotes = useCallback(async (service: Service, id: string) => {
    const key = noteKey(service, id)
    setNotes((n) => ({ ...n, [key]: { state: "loading", content: null } }))
    try {
      const res = await apiFetch(`${service}/${service}/${id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      // No notes file at all comes back as null; an empty one reads the same to a human.
      const raw = typeof data?.metadata_content === "string" ? data.metadata_content.trim() : ""
      setNotes((n) => ({ ...n, [key]: { state: "ready", content: raw || null } }))
    } catch (e) {
      console.error(e)
      setNotes((n) => ({ ...n, [key]: { state: "error", content: null } }))
    }
  }, [])

  // Lazy by design: notes are fetched the first time a row is opened, never on page load.
  useEffect(() => {
    if (openKey && !notes[openKey]) {
      const [service, id] = openKey.split(":")
      loadNotes(service as Service, id)
    }
  }, [openKey, notes, loadNotes])

  async function complete(task: Task) {
    setOpenKey((cur) => (cur === noteKey("tasks", task.id) ? null : cur))
    setCompleting((s) => new Set(s).add(task.id))
    // optimistic remove
    setTasks((prev) => prev.filter((t) => t.id !== task.id))
    try {
      const res = await apiFetch(`tasks/tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "completed" }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      toast.success("Done", { description: task.subject.slice(0, 60) })
    } catch (e) {
      // revert
      setTasks((prev) => [task, ...prev])
      toast.error("Couldn't complete that one")
      console.error(e)
    } finally {
      setCompleting((s) => {
        const n = new Set(s)
        n.delete(task.id)
        return n
      })
    }
  }

  const grouped = GROUPS.map((g) => ({
    ...g,
    items: tasks
      .filter((t) => classifyDue(t.due_date) === g.key)
      .sort((a, b) => {
        if (!a.due_date) return 1
        if (!b.due_date) return -1
        return new Date(a.due_date).getTime() - new Date(b.due_date).getTime()
      }),
  })).filter((g) => g.items.length > 0)

  const overdueCount = tasks.filter((t) => classifyDue(t.due_date) === "overdue").length

  // Every reminder, one-shots included. Recurring ones lead as a block: they are the standing
  // routine and stay in one findable place instead of moving as their next fire time shifts.
  // Inside each block the next thing to fire is on top, and anything without a fire time sinks.
  const upcoming = [...reminders].sort((a, b) => {
    const byKind = Number(isRecurring(b)) - Number(isRecurring(a))
    if (byKind !== 0) return byKind
    if (!a.next_run) return 1
    if (!b.next_run) return -1
    return new Date(a.next_run).getTime() - new Date(b.next_run).getTime()
  })

  return (
    <Tabs value={tab} onValueChange={setTab} className="gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TabsList className="h-8 p-0.5">
          <TabsTrigger value="tasks" className="h-7 gap-1.5 px-2.5 text-xs">
            Tasks
            <span className="text-muted-foreground">{tasks.length}</span>
          </TabsTrigger>
          <TabsTrigger value="reminders" className="h-7 gap-1.5 px-2.5 text-xs">
            Reminders
            <span className="text-muted-foreground">{reminders.length}</span>
          </TabsTrigger>
        </TabsList>
        <div className="flex items-center gap-2">
          {tab === "tasks" && overdueCount > 0 && (
            <Badge variant="outline" className="border-red-500/30 bg-red-500/10 text-red-400 text-xs">
              {overdueCount} overdue
            </Badge>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="h-8 px-2 text-xs"
            onClick={() => load(true)}
            disabled={refreshing}
          >
            <RefreshCwIcon className={`size-3.5 ${refreshing ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      <TabsContent value="tasks">
        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full rounded-xl" />
            ))}
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 rounded-2xl bg-secondary p-8 text-center">
            <CheckCircle2Icon className="size-8 text-green-500" />
            <p className="text-sm font-medium">All clear</p>
            <p className="text-xs text-muted-foreground">No open tasks. Nice.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {grouped.map((g) => (
              <div key={g.key} className="space-y-1.5">
                <div className={`flex items-center gap-1.5 text-xs font-medium ${g.accent}`}>
                  {g.icon}
                  <span>{g.label}</span>
                  <span className="text-muted-foreground">({g.items.length})</span>
                </div>
                <div className="space-y-1.5">
                  {g.items.map((t) => {
                    const rel = relDue(t.due_date)
                    const pri = PRIORITY[t.priority]
                    const busy = completing.has(t.id)
                    const key = noteKey("tasks", t.id)
                    const open = openKey === key
                    return (
                      <div
                        key={t.id}
                        className={`rounded-xl bg-secondary text-sm ${busy ? "opacity-50" : ""}`}
                      >
                        <div className="flex items-start gap-2.5 p-2.5">
                          <Checkbox
                            className="mt-0.5 shrink-0"
                            checked={false}
                            disabled={busy}
                            onCheckedChange={() => complete(t)}
                          />
                          <button
                            type="button"
                            aria-expanded={open}
                            onClick={() => setOpenKey(open ? null : key)}
                            className="min-w-0 flex-1 cursor-pointer text-left"
                          >
                            <p className="leading-snug break-words">{t.subject}</p>
                            {rel.text && (
                              <p className={`mt-0.5 text-xs ${rel.tone}`}>{rel.text}</p>
                            )}
                          </button>
                          {pri && (
                            <span
                              className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${pri.cls}`}
                            >
                              {pri.label}
                            </span>
                          )}
                          <ExpandToggle open={open} onClick={() => setOpenKey(open ? null : key)} />
                        </div>
                        {open && (
                          <NotesPanel notes={notes[key]} onRetry={() => loadNotes("tasks", t.id)} />
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </TabsContent>

      <TabsContent value="reminders">
        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full rounded-xl" />
            ))}
          </div>
        ) : upcoming.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 rounded-2xl bg-secondary p-8 text-center">
            <BellIcon className="size-8 text-muted-foreground" />
            <p className="text-sm font-medium">Nothing scheduled</p>
            <p className="text-xs text-muted-foreground">No reminders waiting to fire.</p>
          </div>
        ) : (
          <div className="space-y-1.5">
            {upcoming.map((r) => {
              const key = noteKey("reminders", r.id)
              const open = openKey === key
              // Violet repeat marks the ones that come back; a one-shot fires once and is gone,
              // so it stays quiet and leads with when, not with its raw "once at ..." schedule.
              const recurring = isRecurring(r)
              return (
                <div key={r.id} className="rounded-xl bg-secondary text-sm">
                  <div className="flex items-start gap-2.5 p-2.5">
                    {recurring ? (
                      <RepeatIcon className="mt-0.5 size-3.5 shrink-0 text-violet-400" />
                    ) : (
                      <BellIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                    )}
                    <button
                      type="button"
                      aria-expanded={open}
                      onClick={() => setOpenKey(open ? null : key)}
                      className="min-w-0 flex-1 cursor-pointer text-left"
                    >
                      <p className="leading-snug break-words">{r.message}</p>
                      <p className="mt-0.5 text-xs break-words text-muted-foreground">
                        {recurring ? (
                          <>
                            {r.schedule}
                            {r.next_run && (
                              <span className="text-violet-300"> · next {relNext(r.next_run)}</span>
                            )}
                          </>
                        ) : (
                          relNext(r.next_run) || "no fire time"
                        )}
                      </p>
                    </button>
                    <ExpandToggle open={open} onClick={() => setOpenKey(open ? null : key)} />
                  </div>
                  {open && (
                    <NotesPanel notes={notes[key]} onRetry={() => loadNotes("reminders", r.id)} />
                  )}
                </div>
              )
            })}
          </div>
        )}
      </TabsContent>
    </Tabs>
  )
}
