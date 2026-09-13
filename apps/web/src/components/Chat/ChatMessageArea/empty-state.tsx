import { cn } from "@/lib/utils";
import { bubbleRadiusStyle } from "../bubble-radius";

// Placeholder bubbles shown while the first page of history is in flight, so a slow
// load reads as a conversation arriving rather than an empty/"needs to sign in" state.
// Mirrors ChatBubble: bg-secondary on the left (agent), bg-primary on the right (you),
// clustered into runs like a real chat. The column is bottom-anchored and overflows the
// top, so it reads as a thread continuing above the fold.
const SKELETON_ROWS: { side: "agent" | "user"; size: string }[] = [
  { side: "agent", size: "h-9 w-40" },
  { side: "agent", size: "h-14 w-56" },
  { side: "user", size: "h-9 w-28" },
  { side: "user", size: "h-9 w-44" },
  { side: "user", size: "h-9 w-24" },
  { side: "agent", size: "h-9 w-48" },
  { side: "agent", size: "h-9 w-32" },
  { side: "user", size: "h-14 w-52" },
  { side: "agent", size: "h-9 w-44" },
  { side: "user", size: "h-9 w-36" },
  { side: "user", size: "h-9 w-28" },
  { side: "agent", size: "h-14 w-60" },
  { side: "agent", size: "h-9 w-36" },
  { side: "user", size: "h-9 w-40" },
];

function ChatSkeleton({ bottomPad }: { bottomPad: number }) {
  return (
    <div
      className="pointer-events-none absolute inset-0 flex flex-col justify-end px-4"
      style={{ paddingBottom: bottomPad }}
    >
      {SKELETON_ROWS.map((row, i) => {
        const isUser = row.side === "user";
        const sameAsPrev = i > 0 && SKELETON_ROWS[i - 1]?.side === row.side;
        const isGroupEnd = SKELETON_ROWS[i + 1]?.side !== row.side;
        return (
          <div
            key={i}
            className={cn(
              "flex",
              isUser ? "justify-end" : "justify-start",
              i > 0 && (sameAsPrev ? "mt-1.5" : "mt-5"),
            )}
          >
            <div
              className={cn(
                "animate-pulse",
                row.size,
                isUser ? "bg-primary" : "bg-secondary",
              )}
              style={bubbleRadiusStyle(isUser, isGroupEnd)}
            />
          </div>
        );
      })}
    </div>
  );
}

// What an empty conversation says: the skeleton while its first page is in flight, then one line.
// Only a direct room speaks for the one agent behind it; a peer or group room has no single agent
// setting anything up, so it stays neutral.
export function ChatEmptyState({
  connected,
  historyLoaded,
  notAuthenticated,
  label,
  direct,
  bottomInset,
}: {
  connected: boolean;
  historyLoaded: boolean;
  notAuthenticated: boolean;
  label: string;
  direct: boolean;
  bottomInset: number;
}) {
  if (connected && !historyLoaded) {
    // The extra 16px mirrors the real list's trailing pb-4 (the typing
    // indicator slot after the last row), so the skeleton's last bubble
    // sits exactly where a real last bubble does.
    return <ChatSkeleton bottomPad={bottomInset + 16} />;
  }
  return (
    <div
      className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center"
      style={{ paddingBottom: bottomInset + 24 }}
    >
      <span className="text-xs text-muted-foreground">
        {!connected
          ? "connecting..."
          : notAuthenticated
            ? `${label} needs to sign in`
            : direct
              ? `${label} is setting things up`
              : "nothing here yet"}
      </span>
    </div>
  );
}
