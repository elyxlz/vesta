import { RefreshCw } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { Account, Usage, UsageCredits, UsageMeter } from "@vesta/core";

function formatResetsAt(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "now";
  const hours = Math.floor(diff / 3_600_000);
  const mins = Math.floor((diff % 3_600_000) / 60_000);
  if (hours > 0) return `in ${String(hours)}h ${String(mins)}m`;
  return `in ${String(mins)}m`;
}

function formatMemberSince(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
  });
}

function AccountSection({ account }: { account: Account }) {
  const rows = [
    { label: "name", value: account.name },
    { label: "email", value: account.email },
    { label: "plan", value: account.plan },
    { label: "organization", value: account.organization },
    {
      label: "member since",
      value: account.created_at ? formatMemberSince(account.created_at) : null,
    },
  ].filter(
    (row): row is { label: string; value: string } => row.value !== null,
  );

  if (rows.length === 0) return null;

  return (
    <div className="flex flex-col gap-2.5">
      <span className="text-sm font-medium text-muted-foreground">account</span>
      <div className="flex flex-col gap-0.5">
        {rows.map((row) => (
          <div
            key={row.label}
            className="-mx-2 flex items-center justify-between gap-4 rounded-md px-2 py-2 text-sm odd:bg-foreground/[0.07]"
          >
            <span className="text-muted-foreground">{row.label}</span>
            <span className="truncate text-foreground">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function UsageBar({ meter }: { meter: UsageMeter }) {
  const pct = meter.used_pct != null ? Math.min(meter.used_pct, 100) : null;
  const resetsAt = meter.resets_at ? formatResetsAt(meter.resets_at) : null;

  if (pct == null) return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{meter.label}</span>
        <span className="text-sm text-muted-foreground tabular-nums">
          {pct.toFixed(0)}%
        </span>
      </div>
      <Progress value={pct} className="h-1.5" />
      {resetsAt && (
        <span className="text-xs text-muted-foreground/60">
          resets {resetsAt}
        </span>
      )}
    </div>
  );
}

function UsageBody({
  meters,
  credits,
  loading,
  error,
}: {
  meters: UsageMeter[];
  credits: UsageCredits | null;
  loading: boolean;
  error: boolean;
}) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-8" />
        </div>
        <Skeleton className="h-1.5 w-full" />
      </div>
    );
  }
  if (error) {
    return (
      <p className="text-sm text-muted-foreground">failed to load usage data</p>
    );
  }
  if (meters.length === 0 && !credits) {
    return (
      <p className="text-sm text-muted-foreground">no usage data available</p>
    );
  }
  return (
    <div className="flex flex-col gap-2.5">
      {meters.map((m) => (
        <UsageBar key={m.label} meter={m} />
      ))}
      {credits && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">credits</span>
          <span className="text-foreground tabular-nums">
            {credits.used != null
              ? `$${credits.used.toFixed(2)}${credits.limit != null ? ` / $${credits.limit.toFixed(2)}` : ""}`
              : "—"}
          </span>
        </div>
      )}
    </div>
  );
}

export function UsageSection({
  usage,
  loading,
  error,
  onRefresh,
}: {
  usage: Usage | null;
  loading: boolean;
  error: boolean;
  onRefresh: () => void;
}) {
  const meters = usage?.meters ?? [];
  const credits = usage?.credits ?? null;
  const account = usage?.account ?? null;

  return (
    <div className="flex flex-col gap-4">
      {account && <AccountSection account={account} />}
      <div className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-muted-foreground">
            plan usage
          </span>
          <button
            onClick={onRefresh}
            aria-label="refresh usage"
            className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            <RefreshCw
              className={`size-3.5 ${loading ? "animate-spin" : ""}`}
            />
          </button>
        </div>
        <UsageBody
          meters={meters}
          credits={credits}
          loading={loading}
          error={error}
        />
      </div>
    </div>
  );
}
