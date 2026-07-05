import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BellRing } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ItemGroup } from "@/components/ui/item";
import { getNotificationHistory, type NotificationEvent } from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { NotificationRow, NotificationRowSkeleton } from "./NotificationRow";
import { useLiveNotifications } from "@/hooks/use-live-notifications";

// Identity for dedupe: notif_id when present (stable across REST history + the live stream),
// falling back to the timestamp for older events that predate notif_id.
function rowKey(event: NotificationEvent): string {
  return event.notif_id ?? event.ts ?? "";
}

// The received-notifications history. Flows at its natural height and scrolls with the settings page;
// the rules cards beside it stay sticky. Live-updating: the row list comes from the REST history
// (paginated), while "pending" is a live set — seeded from the connect snapshot's on-disk ids, plus
// notifications that arrive live, minus ones cleared live. No disk-state polling; a reconnect re-sends
// the snapshot, which re-seeds the set for free.
export function NotificationsCard() {
  const { name: agentName } = useSelectedAgent();
  const { pendingSeed, arrivals, cleared } = useLiveNotifications();

  const [items, setItems] = useState<NotificationEvent[] | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The currently-selected agent, so an in-flight request drops its result if the user switches
  // agents mid-flight (this card is not unmounted on switch, only its effect re-runs).
  const currentAgent = useRef(agentName);
  // Keys of arrivals already in `items`, so live merges don't duplicate a REST-loaded row.
  const seenRef = useRef<Set<string>>(new Set());

  // Pending = on disk, not yet processed: snapshot seed ∪ live arrivals − live clears. A clear after
  // an arrival wins (delete last), so a notification that arrived and was processed isn't pending.
  const pendingIds = useMemo(() => {
    const set = new Set(pendingSeed);
    for (const arrival of arrivals)
      if (arrival.notif_id) set.add(arrival.notif_id);
    for (const id of cleared) set.delete(id);
    return set;
  }, [pendingSeed, arrivals, cleared]);

  // Load (or reload) the newest page of the row list. Stable: only refs + setters.
  const loadFirstPage = useCallback((name: string) => {
    setItems(null);
    setError(null);
    setLoadingMore(false);
    getNotificationHistory(name)
      .then((page) => {
        if (currentAgent.current !== name) return;
        setItems(page.notifications);
        setCursor(page.cursor);
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
    } catch (e) {
      if (currentAgent.current === requestedAgent)
        setError((e as Error).message);
    } finally {
      if (currentAgent.current === requestedAgent) setLoadingMore(false);
    }
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <BellRing className="size-4 text-muted-foreground" />
          recent notifications
        </CardTitle>
        <CardDescription className="text-xs">
          everything the agent has received, and whether each interrupted the
          agent or was snoozed until it was free.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-xs text-destructive">failed to load: {error}</p>
        ) : items === null ? (
          <ItemGroup>
            {Array.from({ length: 4 }).map((_, i) => (
              <NotificationRowSkeleton key={i} />
            ))}
          </ItemGroup>
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
          <div className="flex flex-col gap-2.5">
            <ItemGroup>
              {items.map((event, i) => (
                <NotificationRow
                  key={event.notif_id ?? event.ts ?? `row-${i}`}
                  event={event}
                  // Pending = received but not yet processed (still on disk per the live pending set).
                  isPending={!!event.notif_id && pendingIds.has(event.notif_id)}
                />
              ))}
            </ItemGroup>
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
      </CardContent>
    </Card>
  );
}
