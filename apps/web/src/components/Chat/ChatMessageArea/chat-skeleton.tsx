import { cn } from "@/lib/utils";
import { bubbleRadiusStyle } from "../bubble-radius";
import { CHAT_CONTENT_COLUMN } from "../content-column";

// Placeholder bubbles shown while the first page of history is in flight, so a slow
// load reads as a conversation arriving rather than an empty/"needs to sign in" state.
// Mirrors ChatBubble: bg-bubble on the left (agent), bg-primary on the right (you),
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

export function ChatSkeleton({
  bottomPad,
  isDesktop,
}: {
  bottomPad: number;
  isDesktop: boolean;
}) {
  return (
    <div
      className="pointer-events-none absolute inset-0 flex flex-col justify-end"
      style={{ paddingBottom: bottomPad }}
    >
      <div className={cn("px-4", isDesktop && CHAT_CONTENT_COLUMN)}>
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
                  isUser ? "bg-primary" : "bg-bubble",
                )}
                style={bubbleRadiusStyle(isUser, isGroupEnd)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
