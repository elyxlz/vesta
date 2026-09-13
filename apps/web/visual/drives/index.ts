import type { Scenario } from "../harness/scenario-state";
import { AGENT } from "./agent";
import { AGENT_SETTINGS } from "./agent-settings";
import { APP_SETTINGS } from "./app-settings";
import { CHAT } from "./chat";
import { CHATS } from "./chats";
import { HOME } from "./home";
import { ONBOARDING } from "./onboarding";
import { PAGES } from "./pages";

const AREAS: Record<string, Record<string, Scenario>> = {
  "pages.ts": PAGES,
  "onboarding.ts": ONBOARDING,
  "home.ts": HOME,
  "agent.ts": AGENT,
  "chat.ts": CHAT,
  "chats.ts": CHATS,
  "agent-settings.ts": AGENT_SETTINGS,
  "app-settings.ts": APP_SETTINGS,
};

// Every web scenario by id: its initial state and how to reach the screenshot.
// scenarios.json carries the matching card; the runner owns pixel stability.
export const SCENARIOS: Record<string, Scenario> = Object.fromEntries(
  Object.values(AREAS).flatMap((scenarios) => Object.entries(scenarios)),
);
