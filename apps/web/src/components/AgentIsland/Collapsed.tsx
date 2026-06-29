import { Orb } from "@/components/Orb";
import { cn } from "@/lib/utils";
import type { OrbVisualState } from "@/components/Orb/styles";

type AgentIslandCollapsedProps = {
  name: string;
  orbState: OrbVisualState;
  statusLabel: string;
  error: string;
};

// Self-sized content view (no motion / no layoutId). The shell crossfades whole
// views, so this just renders the collapsed pill content at its natural size.
export function AgentIslandCollapsed({
  name,
  orbState,
  statusLabel,
  error,
}: AgentIslandCollapsedProps) {
  const showStatus = statusLabel && statusLabel !== "alive";
  return (
    <div className="flex h-8 min-w-0 max-w-[min(100vw-2rem,280px)] items-center gap-1.5 px-5">
      <div className="flex shrink-0 items-center justify-center">
        <Orb
          state={orbState}
          size={28}
          suppressMotion
          label={`${name}: ${statusLabel || orbState}`}
        />
      </div>
      <div className="relative -top-0.5 flex min-w-0 flex-1 items-baseline gap-1.5">
        <span className="min-w-0 truncate font-serif text-base font-medium leading-tight tracking-tight sm:text-lg">
          {name}
        </span>
        {showStatus && (
          <span
            className={cn(
              "shrink-0 whitespace-nowrap text-xs",
              error ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {statusLabel}
          </span>
        )}
      </div>
      {/* persistent live region so screen readers hear status changes when collapsed */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {statusLabel}
      </span>
    </div>
  );
}
