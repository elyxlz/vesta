import { Orb } from "@/components/Orb";
import { providerMeta } from "@/components/ProviderPicker/providers";
import { CardDescription, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { OrbVisualState, ProviderIdentity } from "@vesta/core";

interface AgentIslandExpandedProps {
  name: string;
  orbState: OrbVisualState;
  statusLabel: string;
  error: string;
  providerIdentity: ProviderIdentity | null;
}

// Self-sized content view (no motion / no layoutId). The shell crossfades whole
// views, so the provider identity fades in/out with the rest.
export function AgentIslandExpanded({
  name,
  orbState,
  statusLabel,
  error,
  providerIdentity,
}: AgentIslandExpandedProps) {
  return (
    <div className="relative -top-2 flex h-[168px] w-[168px] flex-col items-center justify-center gap-2">
      <div className="flex shrink-0 items-center justify-center">
        <Orb
          state={orbState}
          size={100}
          label={`${name}: ${statusLabel || orbState}`}
        />
      </div>
      <div className="-mt-4 flex flex-col items-center justify-center gap-1 text-center">
        <CardTitle className="line-clamp-2 px-0.5 text-center font-serif text-base font-medium leading-tight tracking-tight sm:text-lg">
          {name}
        </CardTitle>
        <CardDescription
          aria-live="polite"
          className={cn(
            "mt-0.5 line-clamp-3 w-full px-0.5 text-xs leading-snug",
            error ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {statusLabel}
        </CardDescription>
        {providerIdentity && <ProviderLine identity={providerIdentity} />}
      </div>
    </div>
  );
}

function ProviderLine({ identity }: { identity: ProviderIdentity }) {
  const { Logo } = providerMeta(identity.kind);
  const label = identity.modelName
    ? `${identity.providerName} · ${identity.modelName}`
    : identity.providerName;

  return (
    <span
      className="flex max-w-[150px] items-center gap-1 px-0.5 text-[10px] text-muted-foreground"
      title={label}
    >
      <Logo className="size-3 shrink-0" />
      <span className="truncate">{label}</span>
    </span>
  );
}
