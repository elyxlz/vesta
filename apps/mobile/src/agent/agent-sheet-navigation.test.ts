import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import AgentLayout, {
  unstable_settings as agentRoutes,
} from "../../app/agent/[name]/_layout";
import AgentSettingsLayout, {
  unstable_settings as settingsRoutes,
} from "../../app/agent/[name]/(settings)/_layout";

vi.mock("expo-router/stack", () => ({
  default: Object.assign(() => null, { Screen: () => null }),
}));
vi.mock("@/agent/AgentProvider", () => ({ AgentProvider: () => null }));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({ colors: { background: "white", text: "black" } }),
}));

describe("agent sheet navigation", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("presents the entire settings navigator above the anchored agent page", () => {
    const stack = AgentLayout().props.children;
    const sheet = stack.props.children[1];
    expect(agentRoutes.anchor).toBe("index");
    expect(sheet.props.name).toBe("(settings)");
    expect(sheet.props.options).toMatchObject({
      presentation: "formSheet",
      headerShown: false,
      sheetAllowedDetents: [1],
    });
  });

  it("keeps direct-linked details and their back destination in the same sheet", () => {
    const stack = AgentSettingsLayout();
    expect(settingsRoutes.anchor).toBe("settings");
    expect(stack.props.screenOptions.presentation).toBe("card");
    expect(
      stack.props.children.map(
        (screen: ReactElement<{ name: string }>) => screen.props.name,
      ),
    ).toEqual([
      "settings",
      "details/[section]",
      "logs",
      "notifications",
      "file",
    ]);
  });

  it.each(["ios", "android"])(
    "uses the appropriate header inside the %s sheet",
    (platform) => {
      vi.stubEnv("EXPO_OS", platform);
      const stack = AgentSettingsLayout();
      expect(stack.props.screenOptions.headerShown).toBe(platform === "ios");
      const file = stack.props.children.at(-1);
      expect(file.props.name).toBe("file");
      expect(file.props.options).toBeUndefined();
    },
  );
});
