import { Fragment, useCallback, useEffect, useState } from "react";
import { CornerDownRight, Lock, SlidersHorizontal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getNotificationDefaultOverrides,
  getNotificationStaticDefaults,
  setNotificationDefaultOverrides,
  type NotificationDefaultOverride,
  type NotificationStaticDefault,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

type Disposition = "interrupt" | "pool";

interface DefaultRow {
  source: string;
  type: string;
  staticDisposition: Disposition | null;
  override: Disposition | null;
}

// Lowercased to match the engine, which compares (source, type) case-insensitively — so an override
// stored as "Outlook" and a static default observed as "outlook" resolve to the same row.
const overrideKey = (source: string, type: string) =>
  `${source.toLowerCase()}␟${type.toLowerCase()}`;

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

  const rows = buildRows(staticDefaults, overrides);

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

          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
              <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                <CornerDownRight className="size-3.5 text-muted-foreground" />
                fallback behavior
              </span>
              <p className="text-xs leading-relaxed text-muted-foreground">
                how each source behaves when no rule matches. click a badge to
                change it.
              </p>
            </div>
            {loading ? (
              <div className="mx-auto grid min-h-20 w-[98%] grid-cols-[max-content_max-content_minmax(0,1fr)] content-start items-center gap-x-3 gap-y-2">
                <span className="text-[10px] tracking-wide text-muted-foreground/50 uppercase">
                  source
                </span>
                <span className="text-[10px] tracking-wide text-muted-foreground/50 uppercase">
                  type
                </span>
                <span className="justify-self-end text-[10px] tracking-wide text-muted-foreground/50 uppercase">
                  rule
                </span>
                {Array.from({ length: 4 }).map((_, i) => (
                  <Fragment key={i}>
                    <Skeleton className="h-5 w-16 rounded-3xl" />
                    <Skeleton className="h-5 w-14 rounded-3xl" />
                    <Skeleton className="h-5 w-16 justify-self-end rounded-3xl" />
                  </Fragment>
                ))}
              </div>
            ) : rows.length === 0 ? (
              <p className="text-xs text-muted-foreground/70">
                defaults appear here as notifications arrive.
              </p>
            ) : (
              <div className="mx-auto grid min-h-20 w-[98%] grid-cols-[max-content_max-content_minmax(0,1fr)] content-start items-center gap-x-3 gap-y-2">
                <span className="text-[10px] tracking-wide text-muted-foreground/50 uppercase">
                  source
                </span>
                <span className="text-[10px] tracking-wide text-muted-foreground/50 uppercase">
                  type
                </span>
                <span className="justify-self-end text-[10px] tracking-wide text-muted-foreground/50 uppercase">
                  rule
                </span>
                {rows.map((row) => {
                  const effective: Disposition =
                    row.override ?? row.staticDisposition ?? "pool";
                  return (
                    <Fragment key={overrideKey(row.source, row.type)}>
                      <span className="text-sm text-foreground">
                        {row.source}
                      </span>
                      <span className="min-w-0">
                        {row.type ? (
                          <Badge variant="secondary">{row.type}</Badge>
                        ) : (
                          <span className="text-sm text-muted-foreground/50">
                            —
                          </span>
                        )}
                      </span>
                      <span className="flex items-center gap-1.5 justify-self-end">
                        <Badge
                          asChild
                          variant={
                            effective === "interrupt" ? "default" : "secondary"
                          }
                        >
                          <button
                            type="button"
                            aria-label={`default for ${row.source} ${row.type || "(no type)"}: ${
                              effective === "interrupt" ? "interrupt" : "snooze"
                            }, click to toggle`}
                            onClick={() =>
                              toggle(
                                row.source,
                                row.type,
                                effective,
                                row.staticDisposition,
                              )
                            }
                          >
                            {effective === "interrupt" ? "interrupt" : "snooze"}
                          </button>
                        </Badge>
                      </span>
                    </Fragment>
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
