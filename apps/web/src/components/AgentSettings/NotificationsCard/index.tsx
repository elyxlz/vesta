import { useEffect, useMemo, useRef, useState } from "react";
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
import { notificationRowKey } from "@vesta/core";
import { errorMessage } from "@/lib/utils";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { NotificationRow, NotificationRowSkeleton } from "./NotificationRow";
import { useLiveNotifications } from "./use-live-notifications";

// The received-notifications history. Flows at its natural height and scrolls with the settings page;
// the rules cards beside it stay sticky. Live-updating: the row list comes from the REST history
// (paginated), while "pending" is a live set — seeded from the connect snapshot's on-disk ids, plus
// notifications that arrive live, minus ones cleared live. No disk-state polling; a reconnect re-sends
// the snapshot, which re-seeds the set for free.
export function NotificationsCard() {
  const { name: agentName } = useSelectedAgent();
  const { pendingSeed, arrivals, cleared } = useLiveNotifications();

  // The loaded page state is keyed by agent, so a switch reads as empty until its page lands
  // instead of being reset from an effect.
  const [page, setPage] = useState<{
    agent: string;
    items: NotificationEvent[] | null;
    cursor: number | null;
    error: string | null;
  }>({ agent: agentName, items: null, cursor: null, error: null });
  const forAgent = page.agent === agentName;
  const items = forAgent ? page.items : null;
  const cursor = forAgent ? page.cursor : null;
  const error = forAgent ? page.error : null;
  const setItems = (
    update: (prev: NotificationEvent[] | null) => NotificationEvent[] | null,
  ) => {
    setPage((prev) => ({ ...prev, items: update(prev.items) }));
  };
  const [loadingMore, setLoadingMore] = useState(false);
  // The currently-selected agent, so an in-flight request drops its result if the user switches
  // agents mid-flight (this card is not unmounted on switch, only its effect re-runs).
  const currentAgent = useRef(agentName);
  // Keys of arrivals already in `items`, so live merges don't duplicate a REST-loaded row. The key is
  // the arrival, not the pending slot: notif_id alone recurs across time (see notificationRowKey).
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

  // Load the newest page of the row list for the selected agent.
  useEffect(() => {
    if (!agentName) return;
    currentAgent.current = agentName;
    getNotificationHistory(agentName)
      .then((loaded) => {
        if (currentAgent.current !== agentName) return;
        seenRef.current = new Set(loaded.notifications.map(notificationRowKey));
        setPage({
          agent: agentName,
          items: loaded.notifications,
          cursor: loaded.cursor,
          error: null,
        });
      })
      .catch((e: unknown) => {
        if (currentAgent.current === agentName)
          setPage({
            agent: agentName,
            items: null,
            cursor: null,
            error: errorMessage(e, "failed to load notifications"),
          });
      });
  }, [agentName]);

  // Merge live arrivals into the list (newest on top), skipping any already loaded from history.
  // Runs once `items` exists, and again when it (re)loads, catching arrivals that raced the fetch.
  useEffect(() => {
    if (items === null) return;
    const fresh = arrivals.filter(
      (n) => !seenRef.current.has(notificationRowKey(n)),
    );
    if (fresh.length === 0) return;
    fresh.forEach((n) => seenRef.current.add(notificationRowKey(n)));
    setItems((prev) => (prev ? [...[...fresh].reverse(), ...prev] : prev));
  }, [arrivals, items]);

  const loadMore = async () => {
    if (!agentName || cursor === null || loadingMore) return;
    const requestedAgent = agentName;
    setLoadingMore(true);
    try {
      const loaded = await getNotificationHistory(requestedAgent, cursor);
      if (currentAgent.current !== requestedAgent) return;
      loaded.notifications.forEach((n) =>
        seenRef.current.add(notificationRowKey(n)),
      );
      setPage((prev) => ({
        ...prev,
        items: [...(prev.items ?? []), ...loaded.notifications],
        cursor: loaded.cursor,
      }));
    } catch (e) {
      if (currentAgent.current === requestedAgent)
        setPage((prev) => ({
          ...prev,
          error: errorMessage(e, "failed to load notifications"),
        }));
    } finally {
      if (currentAgent.current === requestedAgent) setLoadingMore(false);
    }
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="group-data-[size=sm]/card:text-base">
          <BellRing className="size-4 text-muted-foreground" />
          recent notifications
        </CardTitle>
        <CardDescription className="group-data-[size=sm]/card:text-sm">
          everything the agent has received, and whether each interrupted the
          agent or was snoozed until it was free.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-destructive">failed to load: {error}</p>
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
              {items.map((event) => (
                <NotificationRow
                  key={notificationRowKey(event)}
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
                onClick={() => {
                  void loadMore();
                }}
              >
                {loadingMore ? "loading..." : "load older"}
              </Button>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
