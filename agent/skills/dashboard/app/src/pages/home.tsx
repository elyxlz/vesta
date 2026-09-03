import { useCallback, useEffect, useMemo, useState } from "react"
import { apiFetch } from "@/lib/parent-bridge"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { CalendarIcon, MapPinIcon, RefreshCwIcon } from "lucide-react"
import { TasksAndReminders } from "./tasks"

// The calendar backend (`calendar/upcoming`) is future work: this page codes to the shape it will
// return and, until it exists, treats a 404 as the ordinary empty case rather than an error.
interface CalendarEvent {
  id: string
  title: string
  // ISO datetime for timed events; `YYYY-MM-DD` for all-day events.
  start: string
  end: string
  allDay: boolean
  location: string | null
}

const DAY = 86400000

function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning"
  if (hour < 18) return "Good afternoon"
  return "Good evening"
}

// All-day starts arrive as `YYYY-MM-DD`; parse them as a local calendar day so an event never
// slips a day across a timezone offset (which `new Date("2026-08-25")` would, parsing as UTC).
function eventStart(ev: CalendarEvent): Date {
  if (ev.allDay) {
    const [y, m, d] = ev.start.split("-").map(Number)
    return new Date(y, (m || 1) - 1, d || 1)
  }
  return new Date(ev.start)
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

// "Today" / "Tomorrow" for the near days, otherwise the weekday and date. The near days keep a
// muted date beside the label so the headline stays legible without losing the exact day.
function dayLabel(dayStart: Date, today: Date): { label: string; sub: string } {
  const diff = Math.round((dayStart.getTime() - today.getTime()) / DAY)
  const full = dayStart.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })
  if (diff === 0) return { label: "Today", sub: dayStart.toLocaleDateString(undefined, { day: "numeric", month: "long" }) }
  if (diff === 1) return { label: "Tomorrow", sub: dayStart.toLocaleDateString(undefined, { day: "numeric", month: "long" }) }
  return { label: full, sub: "" }
}

interface DayGroup {
  key: number
  label: string
  sub: string
  items: CalendarEvent[]
}

function groupByDay(events: CalendarEvent[]): DayGroup[] {
  const today = startOfDay(new Date())
  const buckets = new Map<number, CalendarEvent[]>()
  for (const ev of events) {
    const key = startOfDay(eventStart(ev)).getTime()
    const list = buckets.get(key) ?? []
    list.push(ev)
    buckets.set(key, list)
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([key, items]) => {
      const { label, sub } = dayLabel(new Date(key), today)
      // All-day events lead the day, then timed events in chronological order.
      const sorted = [...items].sort((a, b) => {
        if (a.allDay !== b.allDay) return a.allDay ? -1 : 1
        return eventStart(a).getTime() - eventStart(b).getTime()
      })
      return { key, label, sub, items: sorted }
    })
}

function EventRow({ ev }: { ev: CalendarEvent }) {
  const time = ev.allDay
    ? null
    : eventStart(ev).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  return (
    <div className="flex items-start gap-3 rounded-lg px-2 py-1.5 transition-colors hover:bg-secondary/60">
      <div className="w-16 shrink-0 pt-0.5">
        {ev.allDay ? (
          <Badge variant="secondary" className="px-1.5 py-0 text-[10px] font-medium text-muted-foreground">
            all-day
          </Badge>
        ) : (
          <span className="text-xs tabular-nums text-muted-foreground">{time}</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm leading-snug">{ev.title}</p>
        {ev.location && (
          <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground">
            <MapPinIcon className="size-3 shrink-0" />
            <span className="truncate">{ev.location}</span>
          </p>
        )}
      </div>
    </div>
  )
}

function Agenda() {
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) setRefreshing(true)
    try {
      const res = await apiFetch("calendar/upcoming")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setEvents(Array.isArray(data) ? data : [])
    } catch {
      // The endpoint is expected to be absent until the calendar backend ships. A missing calendar
      // is the normal upstream case, so it falls through to the empty state, never a toast or crash.
      setEvents([])
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load(false)
  }, [load])

  const groups = useMemo(() => groupByDay(events), [events])

  return (
    <Card size="sm" className="gap-0! py-0!">
      <CardHeader className="flex! items-center justify-between border-b py-3! px-4!">
        <CardTitle className="flex items-center gap-2 text-sm">
          <CalendarIcon className="size-4 text-muted-foreground" />
          Upcoming
        </CardTitle>
        <CardAction className="self-center">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={() => load(true)}
            disabled={refreshing}
            aria-label="Refresh agenda"
          >
            <RefreshCwIcon className={refreshing ? "animate-spin" : undefined} data-icon="inline-start" />
            Refresh
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="p-4">
        {loading ? (
          <div className="flex flex-col gap-4">
            {Array.from({ length: 2 }).map((_, gi) => (
              <div key={gi} className="flex flex-col gap-2">
                <Skeleton className="h-3.5 w-24" />
                {Array.from({ length: 2 }).map((_, ri) => (
                  <div key={ri} className="flex items-start gap-3 px-2">
                    <Skeleton className="h-3.5 w-14 shrink-0" />
                    <Skeleton className="h-3.5 flex-1" />
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : groups.length === 0 ? (
          <Empty className="border-0 py-8">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <CalendarIcon />
              </EmptyMedia>
              <EmptyTitle className="text-base">No upcoming events</EmptyTitle>
              <EmptyDescription>Your schedule is clear.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex flex-col gap-4">
            {groups.map((g) => (
              <div key={g.key} className="flex flex-col gap-1">
                <div className="flex items-baseline gap-2 px-2">
                  <span className="text-xs font-medium">{g.label}</span>
                  {g.sub && <span className="text-xs text-muted-foreground">{g.sub}</span>}
                </div>
                <div className="flex flex-col gap-0.5">
                  {g.items.map((ev) => (
                    <EventRow key={ev.id} ev={ev} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// Its own ticking component so only the clock re-renders each second, not the whole page
// (agenda + tasks). `tabular-nums` keeps the width steady so the digits don't jitter.
function LiveTime() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(id)
  }, [])
  return (
    <span className="shrink-0 self-center font-heading text-2xl font-semibold leading-none tracking-tight tabular-nums sm:text-3xl">
      {now.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })}
    </span>
  )
}

export function HomePage() {
  // Time-aware and locale-aware, but deliberately name-free: this page is upstreamed to every
  // agent, so the greeting stays generic rather than personal.
  const now = new Date()
  const greeting = greetingFor(now.getHours())
  const fullDate = now.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  })

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 px-4">
        <div className="flex flex-col gap-0.5">
          <h1 className="font-heading text-xl font-semibold tracking-tight">{greeting}</h1>
          <p className="text-sm text-muted-foreground">{fullDate}</p>
        </div>
        <LiveTime />
      </header>

      <Agenda />

      <section className="flex flex-col gap-2">
        <h2 className="px-4 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Tasks &amp; reminders
        </h2>
        <Card size="sm" className="gap-0! py-0!">
          <CardContent className="p-4">
            <TasksAndReminders />
          </CardContent>
        </Card>
      </section>
    </div>
  )
}
