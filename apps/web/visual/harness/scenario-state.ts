import type { Page } from "@playwright/test";
import type { VestaEvent } from "@vesta/core";
import type { RouteFixture } from "./http-fixtures";
import type { SyncFixture } from "./sync-fixtures";

// Everything a web scenario declares about the world before it is driven: the
// route it opens, the sync tree it sees, the gateway answers, the chat socket,
// stored client state, and the native shell. All optional; the defaults are a
// connected browser on the /new wizard with an empty roster.
export interface ScenarioState {
  route?: string;
  sync?: SyncFixture;
  routes?: RouteFixture[];
  chatSocket?: { agent: string; events: VestaEvent[] };
  // Extra localStorage keys on top of the saved connection and the theme.
  storage?: Record<string, string>;
  // false leaves no saved connection, which is how the connect page is reached.
  connection?: boolean;
  native?: {
    platform?: "darwin" | "win32";
    appUpdate?: { available: boolean; version: string };
  };
}

// The imperative half of a scenario: how to reach the state and how to know it
// settled. The card data lives in scenarios.json, keyed by the same id.
export interface Scenario {
  state?: ScenarioState;
  drive: (page: Page) => Promise<void>;
  settle: (page: Page) => Promise<void>;
}

// A fixed wall clock so every relative label ("resets in 2h", "last seen 5m
// ago", day stamps) renders the same on every scan. Timers keep running.
export const FIXED_TIME = new Date("2026-08-18T10:00:00Z");
