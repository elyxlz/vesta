import { useCallback, useEffect, useRef, useState } from "react";
import { BellRing } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CardDescription, CardTitle } from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { getNotificationHistory, type NotificationEvent } from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { NotificationRow, NotificationRowSkeleton } from "./NotificationRow";
import { useLiveNotifications } from "./use-live-notifications";

// Identity for dedupe: notif_id when present (stable across REST history + the live stream),
// falling back to the timestamp for older events that predate notif_id.
function rowKey(event: NotificationEvent): string {
  return event.notif_id ?? event.ts ?? "";
}

// The received-notifications history. Flows at its natural height and scrolls with the settings page;
// the rules cards beside it stay sticky. Live-updating: the initial page is fetched over REST, then
// new arrivals and clears stream in over the agent socket. "Pending" is derived from the event log —
// an arrival with no matching `notification_cleared` is still on disk — so no disk-state polling.
export function NotificationsCard({
  onMakeRule,
}: {
  onMakeRule?: (event: NotificationEvent) => void;
}) {
  const { name: agentName } = useSelectedAgent();
  const { arrivals, cleared: liveCleared, connected } = useLiveNotifications();

  const [items, setItems] = useState<NotificationEvent[] | null>(null);
  const [cleared, setCleared] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The currently-selected agent, so an in-flight request drops its result if the user switches
  // agents mid-flight (this card is not unmounted on switch, only its effect re-runs).
  const currentAgent = useRef(agentName);
  // Keys of arrivals already in `items`, so live merges don't duplicate a REST-loaded row.
  const seenRef = useRef<Set<string>>(new Set());
  const prevConnectedRef = useRef(connected);

  // Load (or reload) the newest page and reset derived state. Stable: only refs + setters.
  const loadFirstPage = useCallback((name: string) => {
    setItems(null);
    setError(null);
    setLoadingMore(false);
    getNotificationHistory(name)
      .then((page) => {
        if (currentAgent.current !== name) return;
        setItems(page.notifications);
        setCursor(page.cursor);
        setCleared(new Set(page.cleared));
        seenRef.current = new Set(page.notifications.map(rowKey));
      })
      .catch((e: Error) => {
        if (currentAgent.current === name) setError(e.message);
      });
  }, []);

  useEffect(() => {
    if (!agentName) return;
    currentAgent.current = agentName;
    loadFirstPage(agentName);
  }, [agentName, loadFirstPage]);

  // Merge live arrivals into the list (newest on top), skipping any already loaded from history.
  // Runs once `items` exists, and again when it (re)loads, catching arrivals that raced the fetch.
  useEffect(() => {
    if (items === null) return;
    const fresh = arrivals.filter((n) => !seenRef.current.has(rowKey(n)));
    if (fresh.length === 0) return;
    fresh.forEach((n) => seenRef.current.add(rowKey(n)));
    setItems((prev) => (prev ? [...[...fresh].reverse(), ...prev] : prev));
  }, [arrivals, items]);

  // Fold live clears into the cleared set; rows derive their pending dot from it.
  useEffect(() => {
    if (liveCleared.length === 0) return;
    setCleared((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of liveCleared)
        if (!next.has(id)) {
          next.add(id);
          changed = true;
        }
      return changed ? next : prev;
    });
  }, [liveCleared]);

  // After a reconnect the stream may have gaps, so re-fetch the newest page to resync.
  useEffect(() => {
    const wasConnected = prevConnectedRef.current;
    prevConnectedRef.current = connected;
    if (!wasConnected && connected && agentName && items !== null) {
      loadFirstPage(agentName);
    }
  }, [connected, agentName, items, loadFirstPage]);

  const loadMore = async () => {
    if (!agentName || cursor === null || loadingMore) return;
    const requestedAgent = agentName;
    setLoadingMore(true);
    try {
      const page = await getNotificationHistory(requestedAgent, cursor);
      if (currentAgent.current !== requestedAgent) return;
      page.notifications.forEach((n) => seenRef.current.add(rowKey(n)));
      setItems((prev) => [...(prev ?? []), ...page.notifications]);
      setCursor(page.cursor);
      setCleared((prev) => new Set([...prev, ...page.cleared]));
    } catch (e) {
      if (currentAgent.current === requestedAgent)
        setError((e as Error).message);
    } finally {
      if (currentAgent.current === requestedAgent) setLoadingMore(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 px-0.5">
      <div className="grid gap-1.5 px-4">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <BellRing className="size-4 text-muted-foreground" />
          recent notifications
        </CardTitle>
        <CardDescription className="text-xs">
          everything the agent has received, and whether each interrupted the
          agent or was snoozed until it was free.
        </CardDescription>
      </div>

      {error ? (
        <p className="text-xs text-destructive">failed to load: {error}</p>
      ) : items === null ? (
        <div className="flex flex-col gap-2.5 pt-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <NotificationRowSkeleton key={i} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BellRing />
            </EmptyMedia>
            <EmptyTitle>No notifications yet</EmptyTitle>
            <EmptyDescription>
              They'll show up here as the agent receives them.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="flex flex-col gap-2.5 pt-1">
          {items.map((event, i) => (
            <NotificationRow
              key={event.notif_id ?? event.ts ?? `row-${i}`}
              event={event}
              // Pending = received but not yet processed: an arrival with no matching clear yet.
              isPending={!!event.notif_id && !cleared.has(event.notif_id)}
              onMakeRule={onMakeRule}
            />
          ))}
          {cursor !== null ? (
            <Button
              size="xs"
              variant="outline"
              className="mt-1 self-center"
              disabled={loadingMore}
              onClick={loadMore}
            >
              {loadingMore ? "loading…" : "load older"}
            </Button>
          ) : null}
        </div>
      )}
    </div>
  );
}
