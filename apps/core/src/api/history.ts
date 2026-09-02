import type { HistoryPage } from "../chat/chat-stream-model";
import type { NotificationEvent } from "../protocol/events";
import type { HttpClient } from "../transport/http";
import { agentPath } from "./agents";

function cursorQuery(cursor: number | undefined): URLSearchParams {
  const params = new URLSearchParams();
  if (cursor !== undefined) params.set("cursor", String(cursor));
  return params;
}

// The app-chat service's own paged, id-cursored history (GET .../app-chat/history).
function chatHistoryPath(name: string, cursor?: number): string {
  const query = cursorQuery(cursor).toString();
  return agentPath(name, `/app-chat/history${query ? `?${query}` : ""}`);
}

// The replay-free live chat socket (GET .../app-chat/ws); dialed with the token in the query.
export function chatSocketPath(name: string): string {
  return agentPath(name, "/app-chat/ws");
}

export async function fetchChatHistory(
  http: HttpClient,
  name: string,
  cursor?: number,
): Promise<HistoryPage> {
  return http.json<HistoryPage>(chatHistoryPath(name, cursor));
}

// One page of the agent's internal event history (GET /history?channel=internals).
export async function fetchInternalsHistory(
  http: HttpClient,
  name: string,
  cursor?: number,
): Promise<HistoryPage> {
  const params = cursorQuery(cursor);
  params.set("channel", "internals");
  return http.json<HistoryPage>(
    agentPath(name, `/history?${params.toString()}`),
  );
}

// One page of received notifications, newest first (GET /history?channel=notifications). Pass the
// returned `cursor` to fetch the next older page; a null cursor means there are no older ones.
// Pending state is not derived here: the connect snapshot seeds it and deltas keep it live.
export async function getNotificationHistory(
  http: HttpClient,
  name: string,
  cursor?: number,
): Promise<{ notifications: NotificationEvent[]; cursor: number | null }> {
  const params = cursorQuery(cursor);
  params.set("channel", "notifications");
  const response = await http.json<HistoryPage>(
    agentPath(name, `/history?${params.toString()}`),
  );
  const notifications = response.events.filter(
    (event): event is NotificationEvent => event.type === "notification",
  );
  // Newest-first for the view; the history endpoint returns ascending within a page.
  notifications.reverse();
  return { notifications, cursor: response.cursor };
}
