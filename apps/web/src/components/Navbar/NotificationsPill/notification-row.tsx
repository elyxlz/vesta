import {
  Bell,
  Activity,
  CircleAlert,
  CircleArrowUp,
  MessageSquare,
  MonitorSmartphone,
  Sparkles,
  SquareCheck,
  type LucideIcon,
} from "lucide-react";
import { memo } from "react";
import {
  PILL_FALLBACK_ICON,
  PILL_KIND_ICONS,
  pillDisplayLine,
  type LoggedUserNotification,
  type AgentRow,
} from "@vesta/core";
import { useAgentVisualStatus } from "@vesta/core/react";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { Orb } from "@/components/Orb";
import { cn } from "@/lib/utils";

// The dialog's unseen/seen boundary, styled as the day separators are.
export function SectionLabel({ text }: { text: string }) {
  return (
    <div className="px-2 pt-5 pb-3 text-center text-xs text-muted-foreground">
      {text}
    </div>
  );
}

// Rows carry the time alone; the day lives in the date separators above them.

// Rows carry the time alone; the day lives in the date separators above them.
const TIME_FORMAT = new Intl.DateTimeFormat([], {
  hour: "2-digit",
  minute: "2-digit",
});

function formatTimestamp(atSeconds: number): string {
  return TIME_FORMAT.format(new Date(atSeconds * 1000));
}

export const NotificationRow = memo(function NotificationRow({
  entry,
  row,
  timestamp,
  compact,
  dimmed,
  banded,
  onOpen,
}: {
  entry: LoggedUserNotification;
  /** The roster agent this notification names, resolved by the list; null if none. */
  row: AgentRow | null;
  timestamp: boolean;
  compact: boolean;
  /** Already-seen rows in the dialog sit back; hovering lifts them for reading. */
  dimmed: boolean;
  /** Alternating dialog rows carry a faint band, as the backups list does. */
  banded: boolean;
  onOpen: (entry: LoggedUserNotification) => void;
}) {
  // The pill's leading-glyph rule, identically: the orb when the notification
  // names a roster agent (who, at their current state), the kind icon
  // otherwise (what).
  const { orbState } = useAgentVisualStatus(
    useOptionalController(),
    row,
    row?.activityState ?? "idle",
  );
  return (
    <button
      type="button"
      className={cn(
        "flex w-full gap-2.5 overflow-hidden rounded-xl px-2 text-left hover:bg-muted",
        compact ? "items-center py-1.5" : "items-start py-2.5",
        dimmed && "opacity-60 transition-opacity hover:opacity-100",
        banded && "bg-foreground/[0.07]",
      )}
      onClick={() => {
        onOpen(entry);
      }}
    >
      {row ? (
        <span className="shrink-0">
          <Orb
            state={orbState}
            size={22}
            suppressMotion
            label={entry.agent}
            glow={0.5}
          />
        </span>
      ) : (
        <PillKindIcon kind={entry.kind} />
      )}
      {compact ? (
        <div className="min-w-0 flex-1 truncate text-[13px]">
          {pillDisplayLine(entry)}
        </div>
      ) : (
        // The dialog reads in full: the title on its own line, the body
        // wrapping below it up to a few lines.
        <div className="min-w-0 flex-1 text-sm">
          <div className="truncate font-medium">{entry.title}</div>
          {entry.body && (
            <div className="mt-0.5 line-clamp-3 text-[13px] text-muted-foreground">
              {entry.body}
            </div>
          )}
        </div>
      )}
      {timestamp && (
        <span className="shrink-0 pt-0.5 text-[10px] text-muted-foreground">
          {formatTimestamp(entry.at)}
        </span>
      )}
    </button>
  );
});

export function PillKindIcon({ kind }: { kind: string }) {
  const name = PILL_KIND_ICONS[kind] ?? PILL_FALLBACK_ICON;
  const Icon = ICON_COMPONENTS[name] ?? Bell;
  return <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />;
}

// This app's rendering of the core icon names (PILL_KIND_ICONS): the shared
// vocabulary is view-independent, and each view maps it onto its own icon set.
const ICON_COMPONENTS: Record<string, LucideIcon> = {
  "message-square": MessageSquare,
  "circle-alert": CircleAlert,
  "square-check": SquareCheck,
  activity: Activity,
  sparkles: Sparkles,
  "circle-arrow-up": CircleArrowUp,
  "monitor-smartphone": MonitorSmartphone,
  bell: Bell,
};

// The navbar's ambient notification surface, anchored beside the leading
// buttons: an idle bell button that morphs into the pill while notifications
// rotate through, and back once the queue drains. Tapping a shown notification
// opens its agent; tapping the idle bell opens a compact popover of recent
// history under the button, whose "see more" expands into the full dialog over
// the durable log. All state lives in NotificationsPillProvider (mounted above
// the route layouts, so navigation never resets it); this component is only
// the web rendering.
