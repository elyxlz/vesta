import type { Scenario } from "../harness/scenario-state";
import { AGENT } from "./agent";
import { HOME } from "./home";
import { CHAT } from "./chat";
import { AGENT_SETTINGS } from "./agent-settings";
import { APP_SETTINGS } from "./app-settings";
import { ONBOARDING } from "./onboarding";

function reference(
  scenarios: Record<string, Scenario>,
  id: string,
  navigation: boolean | string = false,
): Scenario {
  const fixture = scenarios[id];
  if (!fixture) throw new Error(`Missing page fixture: ${id}`);
  return {
    state: fixture.state,
    drive:
      typeof navigation === "string"
        ? async (page) => {
            await page
              .getByRole("tab", { name: navigation, exact: true })
              .click();
          }
        : navigation
          ? fixture.drive
          : () => Promise.resolve(),
  };
}

// Stable page identities, with fixtures reused as data. A page never scrolls
// to a named card or checks its contents to decide whether it is capturable.
export const PAGES: Record<string, Scenario> = {
  "page-home": reference(HOME, "home-many-agents"),
  "page-chat": reference(CHAT, "chat-populated"),
  "page-dashboard": reference(AGENT, "agent-dashboard-live", true),
  "page-settings": reference(APP_SETTINGS, "app-settings-devices"),
  "page-agent-general": reference(AGENT_SETTINGS, "settings-general"),
  "page-agent-provider": reference(
    AGENT_SETTINGS,
    "settings-provider-claude",
    "provider",
  ),
  "page-agent-voice": reference(
    AGENT_SETTINGS,
    "settings-voice-enabled",
    "voice",
  ),
  "page-agent-notifications": reference(
    AGENT_SETTINGS,
    "settings-notifications-list",
    "notifications",
  ),
  "page-agent-files": reference(
    AGENT_SETTINGS,
    "settings-files-simple",
    "files",
  ),
  "page-agent-logs": reference(CHAT, "logs-lines"),
  "page-notifications": reference(HOME, "notifications-dialog", true),
  "page-connect": reference(APP_SETTINGS, "connect-form"),
  "page-connect-link": reference(APP_SETTINGS, "connect-form", true),
  "page-recent-gateways": reference(
    APP_SETTINGS,
    "connect-recent-gateways",
    true,
  ),
  "page-new-agent": reference(ONBOARDING, "name-empty"),
  "page-setup-provider": reference(ONBOARDING, "provider-choice", true),
  "page-setup-auth": reference(ONBOARDING, "provider-oauth", true),
  "page-setup-model": reference(ONBOARDING, "provider-model", true),
  "page-setup-personality": reference(ONBOARDING, "personality-default", true),
  "page-whats-new": reference(APP_SETTINGS, "whats-new-notes", true),
  "page-gateway-logs": reference(
    APP_SETTINGS,
    "app-settings-gateway-logs",
    true,
  ),
  "page-diagnostics": reference(APP_SETTINGS, "debug-page"),
};
