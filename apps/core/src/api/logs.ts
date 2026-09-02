import { agentPath } from "./agents";

// The agent log SSE stream (GET .../logs). `tail` is how many recent lines to replay before
// following; a reconnect asks for none, since the replayed block is already on screen.
export function agentLogsPath(name: string, tail?: number): string {
  const query = tail === undefined ? "" : `?tail=${String(tail)}`;
  return agentPath(name, `/logs${query}`);
}

// The gateway's own log SSE stream (GET /gateway/logs), followed live when asked.
export function gatewayLogsPath(follow: boolean): string {
  return follow ? "/gateway/logs?follow=true" : "/gateway/logs";
}
