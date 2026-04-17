import { useEffect } from "react";
import { Activity, RefreshCw } from "lucide-react";
import {
  Field,
  FieldContent,
  FieldLabel,
} from "@/components/ui/field";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { RateLimit } from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useSettings } from "@/stores/use-settings";

function formatResetsAt(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "now";
  const hours = Math.floor(diff / 3_600_000);
  const mins = Math.floor((diff % 3_600_000) / 60_000);
  if (hours > 0) return `in ${hours}h ${mins}m`;
  return `in ${mins}m`;
}

function UsageBar({ label, limit }: { label: string; limit: RateLimit }) {
  const pct =
    limit.utilization != null ? Math.min(limit.utilization, 100) : null;
  const resetsAt = limit.resets_at ? formatResetsAt(limit.resets_at) : null;

  if (pct == null) return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {pct.toFixed(0)}%
        </span>
      </div>
      <Progress value={pct} className="h-1.5" />
      {resetsAt && (
        <span className="text-[10px] text-muted-foreground/60">
          Resets {resetsAt}
        </span>
      )}
    </div>
  );
}

export function PlanUsage() {
  const { name: agentName } = useSelectedAgent();
  const utilizationMap = useSettings((s) => s.utilization);
  const loading = useSettings((s) => s.usageLoading);
  const error = useSettings((s) => s.usageError);
  const refreshUsageAction = useSettings((s) => s.refreshUsage);
  const utilization = agentName ? (utilizationMap[agentName] ?? null) : null;

  const refresh = () => {
    if (agentName) refreshUsageAction(agentName);
  };

  useEffect(() => {
    if (agentName && !utilization && !error) refresh();
  }, [agentName, utilization, error]);

  const bars: { label: string; limit: RateLimit }[] = [];
  if (utilization?.five_hour)
    bars.push({ label: "current session", limit: utilization.five_hour });
  if (utilization?.seven_day)
    bars.push({ label: "current week", limit: utilization.seven_day });
  if (utilization?.seven_day_sonnet)
    bars.push({
      label: "current week (sonnet)",
      limit: utilization.seven_day_sonnet,
    });
  if (utilization?.seven_day_opus)
    bars.push({
      label: "current week (opus)",
      limit: utilization.seven_day_opus,
    });

  return (
    <Card size="sm">
      <CardContent>
        <Field orientation="vertical" className="gap-3">
          <Field
            orientation="horizontal"
            className="items-center justify-between"
          >
            <FieldContent>
              <FieldLabel className="flex items-center gap-2">
                <Activity className="size-4 text-muted-foreground" />
                plan usage
              </FieldLabel>
            </FieldContent>
            <button
              onClick={refresh}
              className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              <RefreshCw
                className={`size-3.5 ${loading ? "animate-spin" : ""}`}
              />
            </button>
          </Field>

          {loading ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-8" />
              </div>
              <Skeleton className="h-1.5 w-full" />
            </div>
          ) : error ? (
            <p className="text-xs text-muted-foreground">
              failed to load usage data
            </p>
          ) : bars.length === 0 && !utilization?.extra_usage ? (
            <p className="text-xs text-muted-foreground">
              no usage data available
            </p>
          ) : (
            <div className="flex flex-col gap-2.5">
              {bars.map((b) => (
                <UsageBar key={b.label} label={b.label} limit={b.limit} />
              ))}
              {utilization?.extra_usage &&
                utilization.extra_usage.is_enabled && (
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">extra credits</span>
                    <span className="text-foreground tabular-nums">
                      {utilization.extra_usage.used_credits != null &&
                      utilization.extra_usage.monthly_limit != null
                        ? `$${(utilization.extra_usage.used_credits / 100).toFixed(2)} / $${(utilization.extra_usage.monthly_limit / 100).toFixed(2)}`
                        : "—"}
                    </span>
                  </div>
                )}
            </div>
          )}
        </Field>
      </CardContent>
    </Card>
  );
}
