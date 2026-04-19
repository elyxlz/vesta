import { useState, useEffect, useCallback } from "react"
import { Bar, BarChart, XAxis, YAxis, ReferenceLine, Cell, ComposedChart, Area } from "recharts"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { apiFetch } from "@/lib/parent-bridge"
import { BrainIcon, ClockIcon, ActivityIcon, MoonIcon, PlayIcon, Volume2Icon, WrenchIcon, SparklesIcon, MessageCircleIcon, TerminalIcon } from "lucide-react"

interface HistoryEntry {
  time: string
  percentage: number
  duration_s?: number
  out_tok?: number
}

interface TimeseriesEntry {
  time: string
  pct?: number | null
  dur_min?: number
  dur_avg?: number
  dur_max?: number
  turn_count?: number
}

interface ContextData {
  percentage: number
  tokens: number
  max_tokens: number
  nap_status: string
  next_threshold: string
  uptime: string
  history: HistoryEntry[]
  timeseries?: TimeseriesEntry[]
  nap?: NapSection
}

interface NapConfig {
  enabled: boolean
  soft_pct: number
  hard_pct: number
  idle_minutes: number
  cooldown_minutes: number
}

interface NapSection {
  config: NapConfig
  idle_seconds: number | null
  trigger_pending: boolean
}

function formatNumber(n: number): string { return n.toLocaleString() }

function statusBg(s: string): string {
  if (s === "ok") return "bg-green-500/10 text-green-500"
  if (s === "warning") return "bg-yellow-500/10 text-yellow-500"
  return "bg-red-500/10 text-red-500"
}

function estimateNapTime(history: { percentage: number }[], softLimit: number): string | null {
  if (history.length < 3) return null
  const recent = history.slice(-6)
  const first = recent[0], last = recent[recent.length - 1]
  const steps = recent.length - 1
  if (steps <= 0) return null
  const pctPerStep = (last.percentage - first.percentage) / steps
  if (pctPerStep <= 0) return "stable"
  const remaining = softLimit - last.percentage
  if (remaining <= 0) return "soon"
  const stepsLeft = remaining / pctPerStep
  const mins = Math.round(stepsLeft * 10)
  if (mins < 60) return `~${mins}m`
  return `~${Math.floor(mins / 60)}h ${mins % 60}m`
}

const chartConfig = {
  percentage: {
    label: "Context",
    color: "var(--color-chart-1)",
  },
} satisfies ChartConfig

const DEFAULT_SOFT_LIMIT = 50
const DEFAULT_HARD_LIMIT = 70

function barColor(pct: number, soft: number, hard: number): string {
  if (pct >= hard) return "var(--color-destructive)"
  if (pct >= soft) return "#eab308"
  return "#22c55e"
}

export default function ContextPage() {
  const [context, setContext] = useState<ContextData | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const r = await apiFetch("context")
      if (r.ok) setContext(await r.json())
    } catch {}
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  const softLimit = context?.nap?.config?.soft_pct ?? DEFAULT_SOFT_LIMIT
  const hardLimit = context?.nap?.config?.hard_pct ?? DEFAULT_HARD_LIMIT
  const napEstimate = context?.history ? estimateNapTime(context.history, softLimit) : null

  if (!context) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-5 h-5 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Top row: usage + (status + uptime merged) + compact nap */}
      <div className="grid gap-2 grid-cols-3">
        <div className="rounded-2xl bg-muted p-3 text-sm">
          <div className="flex items-center gap-1.5 mb-2">
            <BrainIcon className="size-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-medium">usage</span>
          </div>
          <span className={`text-4xl font-semibold ${context.percentage >= hardLimit ? "text-red-500" : context.percentage >= softLimit ? "text-yellow-500" : "text-green-500"}`}>{context.percentage}%</span>
          <p className="text-xs text-muted-foreground mt-1">
            {formatNumber(context.tokens)} / {formatNumber(context.max_tokens)} · next {context.next_threshold}
          </p>
        </div>

        <StatusCard context={context} napEstimate={napEstimate} />


        <CompactNapCard nap={context.nap} onRefresh={fetchData} />
      </div>

      {/* Combined history: context % (left axis) + duration min/avg/max (right axis), 5-min buckets */}
      {(context.timeseries ?? []).length > 0 && (
        <TimeseriesChart
          timeseries={context.timeseries ?? []}
          softLimit={softLimit}
          hardLimit={hardLimit}
        />
      )}

      <AudioCheckCard />

      <ActivityFeed />
    </div>
  )
}

function formatIdle(idle_seconds: number | null | undefined): string {
  if (idle_seconds == null) return "?"
  if (idle_seconds < 60) return `${idle_seconds}s`
  if (idle_seconds < 3600) return `${Math.floor(idle_seconds / 60)}m`
  return `${Math.floor(idle_seconds / 3600)}h${Math.floor((idle_seconds % 3600) / 60)}m`
}

function StatusCard({ context, napEstimate }: { context: ContextData; napEstimate: string | null }) {
  const idleLabel = formatIdle(context.nap?.idle_seconds)
  return (
    <div className="rounded-2xl bg-muted p-3 text-sm flex flex-col">
      <div className="flex items-center gap-1.5 mb-2">
        <ActivityIcon className="size-3.5 text-muted-foreground" />
        <span className="text-xs text-muted-foreground font-medium">status</span>
      </div>
      <div className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-medium self-start ${statusBg(context.nap_status)}`}>
        <div className={`size-2 rounded-full ${context.nap_status === "ok" ? "bg-green-500" : context.nap_status === "warning" ? "bg-yellow-500" : "bg-red-500"}`} />
        {context.nap_status}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-2 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1"><ClockIcon className="size-3" />up {context.uptime}</span>
        <span>· idle {idleLabel}</span>
        {napEstimate && <span>· nap {napEstimate}</span>}
      </div>
    </div>
  )
}

function CompactNapCard({ nap, onRefresh }: { nap?: NapSection; onRefresh: () => void }) {
  const [napping, setNapping] = useState(false)
  const [saving, setSaving] = useState(false)

  async function napNow() {
    setNapping(true)
    try { await apiFetch("context/nap", { method: "POST" }) } catch {}
    setNapping(false)
    onRefresh()
  }

  async function patch(body: Record<string, unknown>) {
    setSaving(true)
    try {
      await apiFetch("context/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    } catch {}
    setSaving(false)
    onRefresh()
  }

  if (!nap) {
    return (
      <div className="rounded-2xl bg-muted p-3 text-sm flex flex-col">
        <div className="flex items-center gap-1.5 mb-2">
          <MoonIcon className="size-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground font-medium">nap</span>
        </div>
        <span className="text-[11px] text-muted-foreground">loading…</span>
      </div>
    )
  }

  const enabled = nap.config.enabled
  const soft = Math.round(nap.config.soft_pct)
  const hard = Math.round(nap.config.hard_pct)
  const softOptions = [20, 30, 40, 50, 60, 70].filter((v) => v < hard)
  const hardOptions = [30, 40, 50, 60, 70, 80, 90].filter((v) => v > soft)
  // Ensure the current value is always in its dropdown even if outside the normal step
  if (!softOptions.includes(soft)) softOptions.push(soft)
  if (!hardOptions.includes(hard)) hardOptions.push(hard)
  softOptions.sort((a, b) => a - b)
  hardOptions.sort((a, b) => a - b)

  return (
    <div className="rounded-2xl bg-muted p-3 text-sm flex flex-col">
      <div className="flex items-center gap-1.5 mb-2">
        <MoonIcon className="size-3.5 text-muted-foreground" />
        <span className="text-xs text-muted-foreground font-medium">nap</span>
        <label className="ml-auto flex items-center gap-1 text-[11px] cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => patch({ enabled: e.target.checked })}
            className="accent-current"
          />
          <span>{enabled ? "auto" : "off"}</span>
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground mb-2">
        <label className="flex items-center gap-1">
          <span>soft</span>
          <select
            value={soft}
            onChange={(e) => patch({ soft_pct: parseInt(e.target.value) })}
            className="bg-background border rounded px-1 py-0.5 text-[11px]"
            disabled={saving}
          >
            {softOptions.map((v) => <option key={v} value={v}>{v}%</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <span>hard</span>
          <select
            value={hard}
            onChange={(e) => patch({ hard_pct: parseInt(e.target.value) })}
            className="bg-background border rounded px-1 py-0.5 text-[11px]"
            disabled={saving}
          >
            {hardOptions.map((v) => <option key={v} value={v}>{v}%</option>)}
          </select>
        </label>
      </div>
      <button
        onClick={napNow}
        disabled={napping || nap.trigger_pending || saving}
        className="mt-auto h-7 text-xs rounded-lg bg-primary text-primary-foreground px-2 flex items-center justify-center gap-1 disabled:opacity-50"
      >
        <PlayIcon className="size-3" />
        {nap.trigger_pending ? "queued" : napping ? "..." : "nap now"}
      </button>
    </div>
  )
}

interface ActivityEvent {
  ts: string
  kind: string
  text: string
}

function ActivityFeed() {
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    async function tick() {
      try {
        const r = await apiFetch("context/activity?limit=60")
        if (!alive) return
        if (r.ok) {
          const data = await r.json()
          setEvents(data.events || [])
          setError(null)
        } else {
          setError(`http ${r.status}`)
        }
      } catch (e) {
        setError(String(e))
      }
    }
    tick()
    const iv = setInterval(tick, 2000)
    return () => { alive = false; clearInterval(iv) }
  }, [])

  // Auto-scroll to bottom (newest) when events update
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null)
  useEffect(() => {
    if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight
  }, [events, scrollEl])

  return (
    <div className="rounded-2xl bg-muted p-3 flex flex-col h-[180px]">
      <div className="flex items-center gap-1.5 mb-2">
        <BrainIcon className="size-3.5 text-muted-foreground" />
        <span className="text-xs text-muted-foreground font-medium">brain activity</span>
        {error && <span className="text-[10px] text-red-500 ml-2">{error}</span>}
        <span className="ml-auto text-[10px] text-muted-foreground">{events.length}</span>
      </div>
      <div
        ref={setScrollEl}
        className="flex-1 overflow-y-auto font-mono text-[11px] leading-relaxed space-y-1 pr-1"
      >
        {events.length === 0 && (
          <div className="text-muted-foreground italic">no recent activity</div>
        )}
        {events.map((ev, i) => (
          <ActivityRow key={`${ev.ts}-${i}`} ev={ev} fade={i < events.length - 12} />
        ))}
      </div>
    </div>
  )
}

function perfBarColor(d: number): string {
  if (d >= 60) return "#ef4444"
  if (d >= 30) return "#eab308"
  return "#22c55e"
}

const TIMESERIES_CHART_CONFIG = {
  pct: { label: "context %", color: "var(--color-chart-1)" },
  dur_min: { label: "dur min (s)", color: "#22c55e" },
  dur_avg: { label: "dur avg (s)", color: "#60a5fa" },
  dur_max: { label: "dur max (s)", color: "#ef4444" },
} satisfies ChartConfig

function TimeseriesChart({ timeseries, softLimit, hardLimit }: {
  timeseries: TimeseriesEntry[]
  softLimit: number
  hardLimit: number
}) {
  const hasDuration = timeseries.some((t) => typeof t.dur_avg === "number")
  const totalTurns = timeseries.reduce((a, t) => a + (t.turn_count ?? 0), 0)

  return (
    <div className="rounded-2xl bg-muted p-3 flex-1 min-h-0 flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-muted-foreground font-medium">history · context % + SDK response time (5 min buckets)</span>
        <span className="text-[10px] text-muted-foreground">{totalTurns} turns</span>
      </div>
      <ChartContainer config={TIMESERIES_CHART_CONFIG} className="flex-1 min-h-0 w-full">
        <ComposedChart data={timeseries} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barGap={0} barCategoryGap="15%">
          <defs>
            <linearGradient id="ctxFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-chart-1)" stopOpacity={0.55} />
              <stop offset="100%" stopColor="var(--color-chart-1)" stopOpacity={0.08} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="time"
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
            interval="preserveStartEnd"
          />
          <YAxis
            yAxisId="left"
            domain={[0, 100]}
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
            tickFormatter={(v) => `${v}%`}
            width={44}
          />
          {hasDuration && (
            <YAxis
              yAxisId="right"
              orientation="right"
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
              tickFormatter={(v) => `${v}s`}
              width={40}
            />
          )}
          <ReferenceLine yAxisId="left" y={softLimit} stroke="#eab308" strokeDasharray="4 4" strokeOpacity={0.6} />
          <ReferenceLine yAxisId="left" y={hardLimit} stroke="#ef4444" strokeDasharray="4 4" strokeOpacity={0.6} />
          <ChartTooltip
            content={<ChartTooltipContent
              formatter={(value, name) => name === "pct" ? `${value}%` : `${value}s`}
            />}
          />
          <Area
            yAxisId="left"
            dataKey="pct"
            type="monotone"
            stroke="var(--color-chart-1)"
            strokeWidth={2}
            fill="url(#ctxFill)"
            isAnimationActive={false}
          />
          {hasDuration && (
            <>
              <Bar yAxisId="right" dataKey="dur_min" fill="#22c55e" radius={[3, 3, 0, 0]} />
              <Bar yAxisId="right" dataKey="dur_avg" fill="#60a5fa" radius={[3, 3, 0, 0]} />
              <Bar yAxisId="right" dataKey="dur_max" fill="#ef4444" radius={[3, 3, 0, 0]} />
            </>
          )}
        </ComposedChart>
      </ChartContainer>
      <div className="flex items-center gap-3 mt-1 text-[10px] text-muted-foreground justify-end">
        <span className="inline-flex items-center gap-1"><span className="size-2 rounded-sm" style={{ background: "var(--color-chart-1)" }} />context %</span>
        <span className="inline-flex items-center gap-1"><span className="size-2 rounded-sm bg-green-500" />min</span>
        <span className="inline-flex items-center gap-1"><span className="size-2 rounded-sm bg-blue-400" />avg</span>
        <span className="inline-flex items-center gap-1"><span className="size-2 rounded-sm bg-red-500" />max</span>
      </div>
    </div>
  )
}

function ActivityRow({ ev, fade }: { ev: ActivityEvent; fade: boolean }) {
  const short = ev.ts.slice(11, 19) // HH:MM:SS
  const cfg = rowStyle(ev.kind, ev.text)
  return (
    <div className={`flex gap-2 ${fade ? "opacity-40" : ""}`}>
      <span className="text-muted-foreground shrink-0">{short}</span>
      <span className={`shrink-0 ${cfg.color}`}>
        {cfg.icon}
      </span>
      <span className={`break-words min-w-0 ${cfg.textColor}`}>
        {cfg.prefix && <span className="text-muted-foreground mr-1">{cfg.prefix}</span>}
        {cfg.body(ev)}
      </span>
    </div>
  )
}

function rowStyle(kind: string, text: string): {
  color: string; textColor: string; icon: React.ReactNode; prefix?: string;
  body: (ev: ActivityEvent) => React.ReactNode;
} {
  if (kind === "THINKING") {
    return {
      color: "text-purple-500",
      textColor: "text-purple-400/80",
      icon: <SparklesIcon className="size-3" />,
      body: (ev) => ev.text || "thinking…",
    }
  }
  if (kind === "TOOL CALL") {
    const done = text.startsWith("done:")
    return {
      color: done ? "text-green-500" : "text-blue-500",
      textColor: "text-foreground/80",
      icon: <WrenchIcon className="size-3" />,
      body: (ev) => ev.text,
    }
  }
  if (kind === "ASSISTANT") {
    return {
      color: "text-yellow-500",
      textColor: "text-foreground/80",
      icon: <BrainIcon className="size-3" />,
      prefix: "internal",
      body: (ev) => ev.text,
    }
  }
  if (kind === "MESSAGE") {
    return {
      color: "text-cyan-500",
      textColor: "text-foreground/80",
      icon: <MessageCircleIcon className="size-3" />,
      body: (ev) => ev.text,
    }
  }
  if (kind === "CLIENT" || kind === "SYSTEM") {
    return {
      color: "text-muted-foreground",
      textColor: "text-muted-foreground",
      icon: <ActivityIcon className="size-3" />,
      body: (ev) => ev.text,
    }
  }
  return {
    color: "text-muted-foreground",
    textColor: "text-foreground/70",
    icon: <TerminalIcon className="size-3" />,
    body: (ev) => `[${kind}] ${ev.text}`,
  }
}

function AudioCheckCard() {
  const [lastSpeakTs, setLastSpeakTs] = useState<number | null>(null)
  const [now, setNow] = useState(Date.now() / 1000)
  const [testing, setTesting] = useState(false)

  // Poll the voice server for the last /tts/speak timestamp
  useEffect(() => {
    let alive = true
    async function tick() {
      try {
        const r = await apiFetch("voice/tts/last-speak")
        if (!alive) return
        if (r.ok) {
          const data = await r.json()
          setLastSpeakTs(data.ts > 0 ? data.ts : null)
        }
      } catch {}
    }
    tick()
    const iv = setInterval(tick, 2000)
    const tickNow = setInterval(() => setNow(Date.now() / 1000), 500)
    return () => { alive = false; clearInterval(iv); clearInterval(tickNow) }
  }, [])

  const secondsAgo = lastSpeakTs == null ? null : Math.max(0, now - lastSpeakTs)
  // "speaking" window: show indicator for ~6s after last /tts/speak call
  const speaking = secondsAgo != null && secondsAgo < 6

  async function playTone() {
    setTesting(true)
    try {
      const Ctx = (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)
      const ctx = new Ctx()
      // Browsers may start context as "suspended" until a user gesture — resume it.
      if (ctx.state === "suspended") await ctx.resume()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = "sine"
      osc.frequency.value = 660
      const t0 = ctx.currentTime
      gain.gain.setValueAtTime(0, t0)
      gain.gain.linearRampToValueAtTime(0.25, t0 + 0.02)
      gain.gain.setValueAtTime(0.25, t0 + 0.35)
      gain.gain.linearRampToValueAtTime(0, t0 + 0.42)
      osc.connect(gain).connect(ctx.destination)
      osc.start(t0)
      osc.stop(t0 + 0.45)
      osc.onended = () => { ctx.close().catch(() => {}); setTesting(false) }
    } catch {
      setTesting(false)
    }
  }

  const statusLabel = speaking
    ? "speaking now"
    : secondsAgo == null
      ? "no tts yet"
      : secondsAgo < 60
        ? `${Math.round(secondsAgo)}s ago`
        : secondsAgo < 3600
          ? `${Math.floor(secondsAgo / 60)}m ago`
          : `${Math.floor(secondsAgo / 3600)}h ago`

  return (
    <div className="rounded-2xl bg-muted p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="relative flex items-center">
            <Volume2Icon className={`size-4 transition-colors ${speaking ? "text-green-500" : "text-muted-foreground"}`} />
            {speaking && (
              <span className="absolute -right-1 -top-1 size-2 rounded-full bg-green-500 animate-pulse" />
            )}
          </div>
          <div className="flex flex-col">
            <span className="text-xs font-medium">audio</span>
            <span className={`text-[10px] ${speaking ? "text-green-500" : "text-muted-foreground"}`}>
              last tts: {statusLabel}
            </span>
          </div>
        </div>
        <button
          onClick={playTone}
          disabled={testing}
          className="h-8 text-xs rounded-lg bg-primary text-primary-foreground px-3 flex items-center gap-1.5 disabled:opacity-50"
          title="play a short tone to verify the browser tab is not muted"
        >
          <Volume2Icon className="size-3" />
          {testing ? "..." : "test tone"}
        </button>
      </div>
      <p className="text-[10px] text-muted-foreground mt-2">
        no sound? tab is probably muted. right-click the tab → unmute, or ctrl+M.
      </p>
    </div>
  )
}

