import { useEffect, useState, useCallback } from "react"
import { apiFetch } from "@/lib/parent-bridge"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { toast } from "sonner"
import {
  RefreshCwIcon,
  AlertTriangleIcon,
  CalendarClockIcon,
  CalendarIcon,
  InboxIcon,
  CheckCircle2Icon,
} from "lucide-react"

interface Task {
  id: string
  title: string
  status: string
  priority: number
  due_date: string | null
  created_at: string
  completed_at: string | null
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

export function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [completing, setCompleting] = useState<Set<string>>(new Set())

  const load = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) setRefreshing(true)
    try {
      const res = await apiFetch("tasks/tasks")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: Task[] = await res.json()
      setTasks(Array.isArray(data) ? data.filter((t) => t.status !== "done") : [])
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

  async function complete(task: Task) {
    setCompleting((s) => new Set(s).add(task.id))
    // optimistic remove
    setTasks((prev) => prev.filter((t) => t.id !== task.id))
    try {
      const res = await apiFetch(`tasks/tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "done" }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      toast.success("Done", { description: task.title.slice(0, 60) })
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

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{tasks.length} open</span>
          {overdueCount > 0 && (
            <Badge variant="outline" className="border-red-500/30 bg-red-500/10 text-red-400 text-xs">
              {overdueCount} overdue
            </Badge>
          )}
        </div>
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
                  return (
                    <div
                      key={t.id}
                      className={`flex items-start gap-2.5 rounded-xl bg-secondary p-2.5 text-sm ${
                        busy ? "opacity-50" : ""
                      }`}
                    >
                      <Checkbox
                        className="mt-0.5 shrink-0"
                        checked={false}
                        disabled={busy}
                        onCheckedChange={() => complete(t)}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="leading-snug">{t.title}</p>
                        {rel.text && (
                          <p className={`mt-0.5 text-xs ${rel.tone}`}>{rel.text}</p>
                        )}
                      </div>
                      {pri && (
                        <span
                          className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${pri.cls}`}
                        >
                          {pri.label}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
