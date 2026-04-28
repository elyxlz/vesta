import { useState, useEffect, useCallback } from "react"
import { Bar, BarChart, XAxis, YAxis, ReferenceLine, Cell } from "recharts"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { apiFetch } from "@/lib/parent-bridge"
import { BrainIcon, ClockIcon, ActivityIcon, MoonIcon, PlayIcon } from "lucide-react"

interface ContextData {
  percentage: number
  tokens: number
  max_tokens: number
  nap_status: string
  next_threshold: string
  uptime: string
  history: { time: string; percentage: number }[]
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
      {/* Top row: big percentage + status cards */}
      <div className="grid gap-2 grid-cols-3">
        <div className="rounded-2xl bg-muted p-3 text-sm">
          <div className="flex items-center gap-1.5 mb-2">
            <BrainIcon className="size-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-medium">usage</span>
          </div>
          <span className={`text-4xl font-semibold ${context.percentage >= hardLimit ? "text-red-500" : context.percentage >= softLimit ? "text-yellow-500" : "text-green-500"}`}>{context.percentage}%</span>
          <p className="text-xs text-muted-foreground mt-1">
            {formatNumber(context.tokens)} / {formatNumber(context.max_tokens)} tokens
          </p>
        </div>

        <div className="rounded-2xl bg-muted p-3 text-sm">
          <div className="flex items-center gap-1.5 mb-2">
            <ActivityIcon className="size-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-medium">status</span>
          </div>
          <div className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-medium ${statusBg(context.nap_status)}`}>
            <div className={`size-2 rounded-full ${context.nap_status === "ok" ? "bg-green-500" : context.nap_status === "warning" ? "bg-yellow-500" : "bg-red-500"}`} />
            {context.nap_status}
          </div>
          {napEstimate && (
            <p className="text-xs text-muted-foreground mt-2">nap in {napEstimate}</p>
          )}
        </div>

        <div className="rounded-2xl bg-muted p-3 text-sm">
          <div className="flex items-center gap-1.5 mb-2">
            <ClockIcon className="size-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground font-medium">uptime</span>
          </div>
          <span className="text-lg font-semibold">{context.uptime}</span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="rounded-2xl bg-muted p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-muted-foreground font-medium">context fill</span>
          <span className="text-xs text-muted-foreground">{context.next_threshold}</span>
        </div>
        <div className="relative h-4 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full transition-all ${context.percentage >= hardLimit ? "bg-red-500" : context.percentage >= softLimit ? "bg-yellow-500" : "bg-green-500"}`}
            style={{ width: `${Math.min(context.percentage, 100)}%` }}
          />
          <div className="absolute top-0 h-4 border-l-2 border-yellow-500/80" style={{ left: `${softLimit}%` }} />
          <div className="absolute top-0 h-4 border-l-2 border-red-500/80" style={{ left: `${hardLimit}%` }} />
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
          <span>0%</span>
          <span className="text-yellow-500">soft {softLimit}%</span>
          <span className="text-red-500">hard {hardLimit}%</span>
          <span>100%</span>
        </div>
      </div>

      {/* Recharts bar chart */}
      {context.history.length > 1 && (
        <div className="rounded-2xl bg-muted p-3 flex-1 min-h-0 flex flex-col">
          <span className="text-xs text-muted-foreground font-medium mb-2">history</span>
          <ChartContainer config={chartConfig} className="flex-1 min-h-0 w-full">
            <BarChart data={context.history} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <XAxis
                dataKey="time"
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={[0, 60]}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
                tickFormatter={(v) => `${v}%`}
              />
              <ReferenceLine y={softLimit} stroke="#eab308" strokeDasharray="4 4" strokeOpacity={0.6} />
              <ReferenceLine y={hardLimit} stroke="#ef4444" strokeDasharray="4 4" strokeOpacity={0.6} />
              <ChartTooltip
                content={<ChartTooltipContent formatter={(value) => `${value}%`} />}
              />
              <Bar dataKey="percentage" radius={[4, 4, 0, 0]}>
                {context.history.map((entry, i) => (
                  <Cell key={i} fill={barColor(entry.percentage, softLimit, hardLimit)} />
                ))}
              </Bar>
            </BarChart>
          </ChartContainer>
        </div>
      )}

      <NapCard nap={context.nap} onRefresh={fetchData} />
    </div>
  )
}

function NapCard({ nap, onRefresh }: { nap?: NapSection; onRefresh: () => void }) {
  const [local, setLocal] = useState<NapConfig | null>(nap?.config ?? null)
  const [saving, setSaving] = useState(false)
  const [napping, setNapping] = useState(false)

  useEffect(() => {
    if (nap?.config) setLocal(nap.config)
  }, [nap?.config])

  if (!nap || !local) return null

  async function save(patch: Partial<NapConfig>) {
    if (!local) return
    const next = { ...local, ...patch }
    setLocal(next)
    setSaving(true)
    try {
      await apiFetch("context/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) })
    } catch {}
    setSaving(false)
  }

  async function napNow() {
    setNapping(true)
    try {
      await apiFetch("context/nap", { method: "POST" })
    } catch {}
    setNapping(false)
    onRefresh()
  }

  const idleLabel = nap.idle_seconds == null
    ? "unknown"
    : nap.idle_seconds < 60 ? `${nap.idle_seconds}s`
    : nap.idle_seconds < 3600 ? `${Math.floor(nap.idle_seconds / 60)}m`
    : `${Math.floor(nap.idle_seconds / 3600)}h ${Math.floor((nap.idle_seconds % 3600) / 60)}m`

  return (
    <div className="rounded-2xl bg-muted p-3 text-sm space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <MoonIcon className="size-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground font-medium">nap</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">idle {idleLabel}</span>
          <label className="flex items-center gap-1 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={local.enabled}
              onChange={(e) => save({ enabled: e.target.checked })}
              className="accent-current"
            />
            <span>{local.enabled ? "auto" : "off"}</span>
          </label>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <NapSlider label="soft %" value={local.soft_pct} min={20} max={80} step={1}
          onChange={(v) => setLocal({ ...local, soft_pct: v })}
          onCommit={(v) => save({ soft_pct: v })} />
        <NapSlider label="hard %" value={local.hard_pct} min={local.soft_pct + 1} max={90} step={1}
          onChange={(v) => setLocal({ ...local, hard_pct: v })}
          onCommit={(v) => save({ hard_pct: v })} />
      </div>

      <div className="grid grid-cols-2 gap-3 items-end">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">idle (min)</span>
          <input
            type="number" min={1} max={120}
            value={local.idle_minutes}
            onChange={(e) => setLocal({ ...local, idle_minutes: Math.max(1, parseInt(e.target.value) || 1) })}
            onBlur={() => save({ idle_minutes: local.idle_minutes })}
            className="h-8 text-xs rounded-lg border bg-background px-2"
          />
        </label>
        <button
          onClick={napNow}
          disabled={napping || nap.trigger_pending}
          className="h-8 text-xs rounded-lg bg-primary text-primary-foreground px-2 flex items-center justify-center gap-1 disabled:opacity-50"
        >
          <PlayIcon className="size-3" />
          {nap.trigger_pending ? "queued" : napping ? "..." : "nap now"}
        </button>
      </div>

      {saving && <p className="text-[10px] text-muted-foreground">saving...</p>}
    </div>
  )
}

function NapSlider({ label, value, min, max, step, onChange, onCommit }: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void; onCommit: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] text-muted-foreground flex justify-between">
        <span>{label}</span>
        <span>{value.toFixed(0)}</span>
      </span>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        onMouseUp={(e) => onCommit(parseFloat((e.target as HTMLInputElement).value))}
        onTouchEnd={(e) => onCommit(parseFloat((e.target as HTMLInputElement).value))}
        className="w-full accent-current"
      />
    </label>
  )
}
