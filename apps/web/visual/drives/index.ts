import type { Scenario } from "../harness/scenario-state";
import { AGENT } from "./agent";
import { AGENT_SETTINGS } from "./agent-settings";
import { APP_SETTINGS } from "./app-settings";
import { CHAT } from "./chat";
import { HOME } from "./home";
import { ONBOARDING } from "./onboarding";

// Every web scenario by id: the state it starts from, how to reach it, and how
// to know it settled. scenarios.json carries the matching card for each id.
export const SCENARIOS: Record<string, Scenario> = {
  ...ONBOARDING,
  ...HOME,
  ...AGENT,
  ...CHAT,
  ...AGENT_SETTINGS,
  ...APP_SETTINGS,
};
