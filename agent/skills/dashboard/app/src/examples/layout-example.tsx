/**
 * Example page showing the grid layout system.
 *
 * Each widget is a direct child of the page grid — never wrap widgets
 * in their own sub-grid. Most widgets should be col-span-1 (the default).
 *
 * - Default (col-span-1): metric cards, counters, small lists, trackers
 * - col-span-2: charts that need horizontal space to be readable
 * - col-span-full: almost never — only wide data tables with many columns
 */

// --- Small metric card (1 column) ---

function MetricCard({ title, value, change }: { title: string; value: string; change: string }) {
  return (
    <div className="rounded-2xl border border-border bg-muted p-4">
      <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
      <p className="mt-2 text-2xl font-bold">{value}</p>
      <p className="text-xs text-muted-foreground mt-1">{change}</p>
    </div>
  )
}

// --- Bar chart (col-span-2) ---

function WeeklyChart() {
  return (
    <div className="rounded-2xl border border-border bg-muted p-4 col-span-2">
      <h3 className="text-sm font-medium text-muted-foreground">Weekly Activity</h3>
      <div className="mt-4 flex items-end gap-2 h-32">
        {[40, 65, 45, 80, 55, 90, 70].map((h, i) => (
          <div key={i} className="flex-1 rounded-md bg-primary/20" style={{ height: `${h}%` }} />
        ))}
      </div>
      <div className="flex justify-between mt-2 text-xs text-muted-foreground">
        <span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Sun</span>
      </div>
    </div>
  )
}

// --- Task list (1 column) ---

function TaskList() {
  return (
    <div className="rounded-2xl border border-border bg-muted p-4">
      <h3 className="text-sm font-medium text-muted-foreground">Tasks</h3>
      <div className="mt-3 space-y-2">
        {["Review PR #42", "Deploy v2.1", "Update docs"].map((t, i) => (
          <div key={i} className="flex items-center gap-2 text-sm">
            <div className="size-4 rounded border border-muted-foreground/30" />
            <span>{t}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- Event log (col-span-full) ---

function EventLog() {
  const events = [
    { time: "2m ago", event: "Deployment completed", status: "success" },
    { time: "15m ago", event: "Build started", status: "info" },
    { time: "1h ago", event: "Alert triggered: high CPU", status: "warning" },
    { time: "3h ago", event: "User signup spike detected", status: "info" },
  ]

  return (
    <div className="rounded-2xl border border-border bg-muted p-4 col-span-full">
      <h3 className="text-sm font-medium text-muted-foreground">Recent Events</h3>
      <div className="mt-3 divide-y">
        {events.map((e, i) => (
          <div key={i} className="flex items-center justify-between py-2 text-sm">
            <div className="flex items-center gap-3">
              <div className={`size-2 rounded-full ${e.status === "success" ? "bg-green-500" : e.status === "warning" ? "bg-yellow-500" : "bg-blue-500"}`} />
              <span>{e.event}</span>
            </div>
            <span className="text-muted-foreground text-xs">{e.time}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- Page component ---

export function LayoutExamplePage() {
  return (
    <div className="grid gap-4 grid-cols-[repeat(auto-fit,minmax(280px,1fr))]">
      <MetricCard title="Users" value="1,234" change="+12% from last month" />
      <MetricCard title="Revenue" value="$5,678" change="+8% from last month" />
      <MetricCard title="Uptime" value="99.9%" change="Last 30 days" />
      <WeeklyChart />
      <TaskList />
      <EventLog />
    </div>
  )
}
