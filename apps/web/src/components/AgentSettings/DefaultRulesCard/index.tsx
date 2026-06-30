import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronRight,
  CornerDownRight,
  Lock,
  SlidersHorizontal,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getNotificationDefaultOverrides,
  getNotificationStaticDefaults,
  setNotificationDefaultOverrides,
  type NotificationDefaultOverride,
  type NotificationEvent,
  type NotificationStaticDefault,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { cn } from "@/lib/utils";
import { useLiveNotifications } from "@/hooks/use-live-notifications";

type Disposition = "interrupt" | "pool";

const CORE_SOURCE = "core";

// Lowercased to match the engine, which compares (source, type) case-insensitively — so an override
// stored as "Outlook" and a static default observed as "outlook" resolve to the same row.
const overrideKey = (source: string, type: string) =>
  `${source.toLowerCase()}␟${type.toLowerCase()}`;

// Fold live notification arrivals into the fetched static defaults so a new (source, type) appears as
// soon as it arrives, no manual refresh. A notification's own `interrupt` flag is its static baseline
// (what static-defaults aggregates server-side); the newest arrival per pair wins and overrides the
// fetched value. Core is exempt (never shown), and arrivals predating the flag are skipped.
function mergeLiveDefaults(
  base: NotificationStaticDefault[],
  arrivals: NotificationEvent[],
): NotificationStaticDefault[] {
  const byKey = new Map(base.map((d) => [overrideKey(d.source, d.type), d]));
  // Arrivals are oldest-first (the socket appends), so iterate in order and let the latest write win
  // per (source, type) — its interrupt flag is the freshest static baseline, overriding the server one.
  for (const a of arrivals) {
    if (a.source.toLowerCase() === CORE_SOURCE || a.interrupt === undefined)
      continue;
    const type = a.notif_type ?? "";
    byKey.set(overrideKey(a.source, type), {
      source: a.source,
      type,
      interrupt: a.interrupt,
    });
  }
  return [...byKey.values()];
}

interface DefaultRow {
  source: string;
  type: string;
  staticDisposition: Disposition | null;
  override: Disposition | null;
}

// One row per (source, type) the agent has seen, plus any override targeting a (source, type) not in
// history. The effective disposition is the user's override if set, otherwise the source's static
// default. Toggling that equals the static default clears the override (inherit) rather than pinning.
function buildRows(
  staticDefaults: NotificationStaticDefault[],
  overrides: NotificationDefaultOverride[],
): DefaultRow[] {
  const overrideByKey = new Map(
    overrides.map((o) => [overrideKey(o.source, o.type), o.action]),
  );
  const rows: DefaultRow[] = staticDefaults.map((d) => ({
    source: d.source,
    type: d.type,
    staticDisposition: d.interrupt ? "interrupt" : "pool",
    override: overrideByKey.get(overrideKey(d.source, d.type)) ?? null,
  }));
  // Surface overrides whose (source, type) hasn't been observed in history, so they remain visible/undoable.
  const seen = new Set(rows.map((r) => overrideKey(r.source, r.type)));
  for (const o of overrides) {
    if (!seen.has(overrideKey(o.source, o.type))) {
      rows.push({
        source: o.source,
        type: o.type,
        staticDisposition: null,
        override: o.action,
      });
    }
  }
  return rows;
}

const effectiveOf = (row: DefaultRow): Disposition =>
  row.override ?? row.staticDisposition ?? "pool";

interface SourceGroup {
  source: string;
  rows: DefaultRow[];
}

// Group the flat (source, type) rows under their source, so a source with many types reads as one
// block instead of repeating its name on every row. Insertion order is preserved (newest source last).
function groupBySource(rows: DefaultRow[]): SourceGroup[] {
  const bySource = new Map<string, DefaultRow[]>();
  for (const row of rows) {
    const existing = bySource.get(row.source);
    if (existing) existing.push(row);
    else bySource.set(row.source, [row]);
  }
  return [...bySource.entries()].map(([source, sourceRows]) => ({
    source,
    rows: sourceRows,
  }));
}

// One-line at-a-glance tally for a collapsed source, e.g. "3 interrupt · 1 snooze".
function tallyLabel(rows: DefaultRow[]): string {
  let interrupt = 0;
  let snooze = 0;
  for (const row of rows) {
    if (effectiveOf(row) === "interrupt") interrupt += 1;
    else snooze += 1;
  }
  return [
    interrupt ? `${interrupt} interrupt` : "",
    snooze ? `${snooze} snooze` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

// Past this many sources or rows the source groups collapse by default, so a noisy fleet stays scannable.
const DENSE_SOURCES = 6;
const DENSE_ROWS = 12;

// The defaults the rules layer on top of: the immutable core exemption, and the per-(source, type)
// fallback applied when no rule matches. The fallback each source chose is editable here — flip it to
// change the baseline without writing a catch-all rule.
export function DefaultRulesCard() {
  const { name: agentName } = useSelectedAgent();
  const [staticDefaults, setStaticDefaults] = useState<
    NotificationStaticDefault[]
  >([]);
  const [overrides, setOverrides] = useState<NotificationDefaultOverride[]>([]);
  const [loading, setLoading] = useState(true);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Live arrivals so a newly-seen (source, type) shows up without a refresh. Tolerant of no provider
  // (tests): arrivals is [] and the card is REST-only.
  const { arrivals } = useLiveNotifications();

  useEffect(() => {
    if (!agentName) return;
    let cancelled = false;
    setStaticDefaults([]);
    setOverrides([]);
    setLoading(true);
    setSaveError(null);
    Promise.all([
      getNotificationStaticDefaults(agentName),
      getNotificationDefaultOverrides(agentName),
    ])
      .then(([defaults, ovr]) => {
        if (cancelled) return;
        setStaticDefaults(defaults);
        setOverrides(ovr);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentName]);

  const toggle = useCallback(
    async (
      source: string,
      type: string,
      effective: Disposition,
      staticDisposition: Disposition | null,
    ) => {
      if (!agentName) return;
      const next: Disposition =
        effective === "interrupt" ? "pool" : "interrupt";
      const others = overrides.filter(
        (o) => overrideKey(o.source, o.type) !== overrideKey(source, type),
      );
      // Flipping back to the source's own default just clears the override (inherit again).
      const updated =
        next === staticDisposition
          ? others
          : [...others, { source, type, action: next }];
      const previous = overrides;
      setOverrides(updated);
      setSaveError(null);
      try {
        await setNotificationDefaultOverrides(agentName, updated);
      } catch (e) {
        setOverrides(previous);
        setSaveError((e as Error).message);
      }
    },
    [agentName, overrides],
  );

  const liveDefaults = useMemo(
    () => mergeLiveDefaults(staticDefaults, arrivals),
    [staticDefaults, arrivals],
  );
  const rows = useMemo(
    () => buildRows(liveDefaults, overrides),
    [liveDefaults, overrides],
  );
  const groups = useMemo(() => groupBySource(rows), [rows]);

  // Source groups collapse by default once the table is dense; the user can override per-source.
  const dense = groups.length > DENSE_SOURCES || rows.length > DENSE_ROWS;
  const [openState, setOpenState] = useState<Record<string, boolean>>({});
  const isOpen = (source: string) =>
    source in openState ? openState[source] : !dense;
  const toggleOpen = (source: string) =>
    setOpenState((s) => ({ ...s, [source]: !isOpen(source) }));
  const allOpen = groups.every((g) => isOpen(g.source));
  const setAllOpen = (open: boolean) =>
    setOpenState(Object.fromEntries(groups.map((g) => [g.source, open])));

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <SlidersHorizontal className="size-4 text-muted-foreground" />
          defaults
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4 pb-2">
          <div className="flex flex-col gap-1">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
              <Lock className="size-3.5 text-muted-foreground" />
              core notifications
            </span>
            <p className="text-xs leading-relaxed text-muted-foreground">
              the agent's own internal notifications follow their own setting.
              rules can't override them.
            </p>
          </div>

          <div className="flex flex-col gap-2.5">
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                  <CornerDownRight className="size-3.5 text-muted-foreground" />
                  fallback behavior
                </span>
                {dense && !loading && rows.length > 0 ? (
                  <button
                    type="button"
                    className="text-xs text-muted-foreground/70 transition-colors hover:text-foreground"
                    onClick={() => setAllOpen(!allOpen)}
                  >
                    {allOpen ? "collapse all" : "expand all"}
                  </button>
                ) : null}
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
                how each source behaves when no rule matches. tap a badge to
                change it.
              </p>
            </div>
            {loading ? (
              <div className="flex min-h-20 flex-col gap-2.5">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="flex flex-col gap-1.5">
                    <Skeleton className="h-5 w-28 rounded-3xl" />
                    <div className="flex items-center justify-between pl-5">
                      <Skeleton className="h-4 w-20 rounded-3xl" />
                      <Skeleton className="h-5 w-16 rounded-3xl" />
                    </div>
                  </div>
                ))}
              </div>
            ) : rows.length === 0 ? (
              <p className="text-xs text-muted-foreground/70">
                defaults appear here as notifications arrive.
              </p>
            ) : (
              <div className="flex flex-col gap-2.5">
                {groups.map((group) => {
                  const open = isOpen(group.source);
                  return (
                    <div key={group.source} className="flex flex-col gap-1.5">
                      <button
                        type="button"
                        aria-expanded={open}
                        aria-label={`${group.source}, ${group.rows.length} ${group.rows.length === 1 ? "type" : "types"}, ${open ? "collapse" : "expand"}`}
                        onClick={() => toggleOpen(group.source)}
                        className="flex items-center gap-2 text-left"
                      >
                        <ChevronRight
                          className={cn(
                            "size-3.5 shrink-0 text-muted-foreground/60 transition-transform",
                            open && "rotate-90",
                          )}
                        />
                        <span className="text-sm font-semibold text-foreground">
                          {group.source}
                        </span>
                        <span className="text-xs text-muted-foreground/50">
                          {group.rows.length}{" "}
                          {group.rows.length === 1 ? "type" : "types"}
                        </span>
                        {!open ? (
                          <span className="ml-auto truncate text-xs text-muted-foreground/70">
                            {tallyLabel(group.rows)}
                          </span>
                        ) : null}
                      </button>

                      {open ? (
                        <div className="flex flex-col gap-1.5 pl-5">
                          {group.rows.map((row) => {
                            const effective = effectiveOf(row);
                            return (
                              <div
                                key={overrideKey(row.source, row.type)}
                                className="flex items-center gap-2"
                              >
                                <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                                  {row.type || (
                                    <span className="text-muted-foreground/50">
                                      no type
                                    </span>
                                  )}
                                </span>
                                {row.override ? (
                                  <span
                                    className="size-1.5 shrink-0 rounded-full bg-primary/60"
                                    title="you changed this — tap to inherit again"
                                  />
                                ) : null}
                                <Badge
                                  asChild
                                  variant={
                                    effective === "interrupt"
                                      ? "default"
                                      : "secondary"
                                  }
                                >
                                  <button
                                    type="button"
                                    aria-label={`default for ${row.source} ${row.type || "(no type)"}: ${
                                      effective === "interrupt"
                                        ? "interrupt"
                                        : "snooze"
                                    }, tap to toggle`}
                                    onClick={() =>
                                      toggle(
                                        row.source,
                                        row.type,
                                        effective,
                                        row.staticDisposition,
                                      )
                                    }
                                  >
                                    {effective === "interrupt"
                                      ? "interrupt"
                                      : "snooze"}
                                  </button>
                                </Badge>
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
            {saveError ? (
              <p className="text-[10px] text-destructive">{saveError}</p>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
