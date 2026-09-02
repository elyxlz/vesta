import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Item, ItemContent, ItemGroup, ItemMedia } from "@/components/ui/item";
import { cn } from "@/lib/utils";

// A hub cell placeholder, shaped like the Item cells the simple view renders.
function HubRowSkeleton() {
  return (
    <Item variant="muted" size="sm">
      <ItemMedia variant="icon" className="size-9 rounded-[10px] bg-muted">
        <Skeleton className="size-4 rounded" />
      </ItemMedia>
      <ItemContent className="gap-1.5">
        <Skeleton className="h-3.5 w-24 rounded" />
        <Skeleton className="h-3 w-40 max-w-full rounded" />
      </ItemContent>
    </Item>
  );
}

function SkeletonSection({
  label,
  rows,
  className,
}: {
  label: string;
  rows: number;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <p className="px-1 text-[11px] font-medium text-muted-foreground/70">
        {label}
      </p>
      <Card size="sm">
        <CardContent>
          <ItemGroup>
            {Array.from({ length: rows }).map((_, i) => (
              <HubRowSkeleton key={i} />
            ))}
          </ItemGroup>
        </CardContent>
      </Card>
    </div>
  );
}

// Matches SimpleView's bento: mind + shared folders left, skills right; one stacked column on mobile.

// Matches SimpleView's bento: mind + shared folders left, skills right; one stacked column on mobile.
export function SimpleSkeleton({ agentName }: { agentName?: string }) {
  const name = agentName ?? "the agent";
  return (
    <div className="flex flex-col gap-3 p-1 lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-6">
      <div className="contents lg:flex lg:flex-col lg:gap-6">
        <SkeletonSection label={`who ${name} is`} rows={3} />
        <SkeletonSection
          label="shared folders"
          rows={2}
          className="order-3 lg:order-none"
        />
      </div>
      <div className="contents lg:flex lg:flex-col lg:gap-6">
        <SkeletonSection
          label="abilities"
          rows={3}
          className="order-2 lg:order-none"
        />
      </div>
    </div>
  );
}

// Text-like lines of varying width filling the editor area while a file (or the
// whole tab) loads.

// Text-like lines of varying width filling the editor area while a file (or the
// whole tab) loads.
const EDITOR_SKELETON_LINES = [
  82, 64, 90, 48, 73, 88, 40, 67, 95, 56, 78, 44, 84, 61, 70, 50, 86, 38,
];

export function FileEditorSkeleton() {
  return (
    <div className="flex h-full flex-col gap-3 overflow-hidden px-4 py-4">
      {EDITOR_SKELETON_LINES.map((width, i) => (
        <Skeleton
          key={i}
          className="h-3.5 shrink-0 rounded"
          style={{ width: `${String(width)}%` }}
        />
      ))}
    </div>
  );
}

// Reserve the floating nav pill's height so the filled panel clears it (matches
// the flowing tabs' max-md:pb-28 in AgentSettings).
