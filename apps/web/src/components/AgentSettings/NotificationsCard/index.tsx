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
import { notificationRowKey, getNotificationHistory } from "@vesta/core";
import { errorMessage } from "@/lib/utils";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { NotificationRow, NotificationRowSkeleton } from "./NotificationRow";
import { usePendingNotifications } from "./use-pending-notifications";
import type { NotificationEvent } from "@vesta/core";
import { httpClient } from "@/api/client";

// A pending notification the history page does not carry gets a row of its own, above the page: the
// pending list grows at its end as notifications land, so reversing it puts the newest first. A
// pending entry vestad only knows by id carries no timestamp, so a row key alone would not match
// the stored arrival; the notif_id it always carries is what says the page already shows it.
function mergePending(
  history: NotificationEvent[],
  pending: NotificationEvent[],
): NotificationEvent[] {
  const keys = new Set(history.map(notificationRowKey));
  const ids = new Set(
    history.flatMap((event) => (event.notif_id ? [event.notif_id] : [])),
  );
  const missing = pending.filter(
    (event) =>
      !keys.has(notificationRowKey(event)) &&
      !(event.notif_id != null && ids.has(event.notif_id)),
  );
  return missing.length === 0
    ? history
    : [...[...missing].reverse(), ...history];
}

// The received-notifications history. Flows at its natural height and scrolls with the settings page;
// the rules cards beside it stay sticky. The row list comes from the REST history (paginated) merged
// with the pending set the replica carries: the notifications still on disk, whole events. No
// disk-state polling; a reconnect re-sends the snapshot, which re-seeds the set for free.
export function NotificationsCard() {
  const { name: agentName } = useSelectedAgent();
  const pending = usePendingNotifications();

  // The loaded page state is keyed by agent, so a switch reads as empty until its page lands
  // instead of being reset from an effect.
  const [page, setPage] = useState<{
    agent: string;
    items: NotificationEvent[] | null;
    cursor: number | null;
    error: string | null;
  }>({ agent: agentName, items: null, cursor: null, error: null });
  const forAgent = page.agent === agentName;
  const historyItems = forAgent ? page.items : null;
  const cursor = forAgent ? page.cursor : null;
  const error = forAgent ? page.error : null;
  const [loadingMore, setLoadingMore] = useState(false);
  // The currently-selected agent, so an in-flight request drops its result if the user switches
  // agents mid-flight (this card is not unmounted on switch, only its effect re-runs).
  const currentAgent = useRef(agentName);
  // Pending = on disk, not yet processed. A row is marked by id, so a notification the agent has
  // since worked through loses its mark on the next replica delta.
  const pendingIds = useMemo(
    () =>
      new Set(
        pending.flatMap((event) => (event.notif_id ? [event.notif_id] : [])),
      ),
    [pending],
  );
  const items = useMemo(
    () => (historyItems === null ? null : mergePending(historyItems, pending)),
    [historyItems, pending],
  );

  // Load the newest page of the row list for the selected agent.
  useEffect(() => {
    if (!agentName) return;
    currentAgent.current = agentName;
    getNotificationHistory(httpClient, agentName)
      .then((loaded) => {
        if (currentAgent.current !== agentName) return;
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

  const loadMore = async () => {
    if (!agentName || cursor === null || loadingMore) return;
    const requestedAgent = agentName;
    setLoadingMore(true);
    try {
      const loaded = await getNotificationHistory(
        httpClient,
        requestedAgent,
        cursor,
      );
      if (currentAgent.current !== requestedAgent) return;
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
        <CardTitle>
          <BellRing className="size-4 text-muted-foreground" />
          recent notifications
        </CardTitle>
        <CardDescription>
          everything the agent has received, whether each interrupted the agent
          or was snoozed until it was free, and which are still waiting.
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
