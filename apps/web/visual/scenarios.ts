import { expect, type Page } from "@playwright/test";
import type { AgentStatus, Delta } from "@vesta/core";
import { agentDelta, startingAgent } from "./harness/sync-fixtures";
import {
  AGENT,
  type HangEndpoint,
  type ProviderInfoFixture,
} from "./harness/http-fixtures";

// Which gallery group a scenario belongs to: the onboarding flow itself, or the
// settings surfaces captured alongside it. The gallery renders one per section.
export type ScenarioSection = "onboarding" | "settings";

export interface Scenario {
  id: string;
  section: ScenarioSection;
  agentStatus: AgentStatus;
  createResponse: { status: number; body: { error: string } } | null;
  deltas: Delta[];
  hang?: HangEndpoint;
  // A route other than /new, plus the roster agent and provider it reads (the
  // settings change-model dialog needs an existing, provisioned agent).
  route?: string;
  agentName?: string;
  provider?: ProviderInfoFixture;
  drive: (page: Page) => Promise<void>;
  settle: (page: Page) => Promise<void>;
}

const defaults = {
  section: "onboarding" as ScenarioSection,
  agentStatus: "starting" as AgentStatus,
  createResponse: null,
  deltas: [] as Delta[],
};

// A settled agent whose provider is one of the fixed-catalog kinds, used to
// capture the settings change-model dialog those providers show.
function settingsModelScenario(
  id: string,
  kind: ProviderInfoFixture["kind"],
  model: string,
  visibleLabel: string,
): Scenario {
  return {
    ...defaults,
    id,
    section: "settings",
    route: "/agent/luna/settings",
    agentName: "luna",
    provider: {
      kind,
      model,
      resolved_model: model,
      max_context_tokens: 131072,
      authed: true,
      plan: null,
    },
    drive: async (page) => {
      await page.getByRole("button", { name: "change model" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText(visibleLabel)).toBeVisible();
    },
  };
}

async function fillName(page: Page, name: string): Promise<void> {
  await page.getByPlaceholder("name your agent").fill(name);
}

async function submitName(page: Page): Promise<void> {
  await page.getByRole("button", { name: "continue" }).click();
}

async function crossProvider(page: Page): Promise<void> {
  await page.getByText("Z.AI", { exact: true }).click();
  await page.getByPlaceholder("Z.AI subscription key").fill("visual-zai-key");
  await page.getByRole("button", { name: "next" }).click();
  // Z.AI shows its fixed model catalog in onboarding; take the default.
  await page.getByRole("button", { name: "continue" }).click();
}

async function toCreating(page: Page): Promise<void> {
  await fillName(page, AGENT);
  await submitName(page);
  await crossProvider(page);
  await expect(page.getByText("pick a vibe")).toBeVisible();
  await page.getByRole("button", { name: "continue" }).click();
}

export const SCENARIOS: Scenario[] = [
  {
    ...defaults,
    id: "name-empty",
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(page.getByPlaceholder("name your agent")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "continue" }),
      ).toBeDisabled();
    },
  },
  {
    ...defaults,
    id: "name-valid",
    drive: async (page) => {
      await fillName(page, "luna");
    },
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "continue" }),
      ).toBeEnabled();
    },
  },
  {
    ...defaults,
    id: "name-rejected",
    // The create POST fires only after the whole flow is collected, so the
    // driver walks to creating and the 409 bounces back to the name step.
    createResponse: { status: 409, body: { error: "name already taken" } },
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("name already taken")).toBeVisible();
      await expect(page.getByPlaceholder("name your agent")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-choice",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
    },
    settle: async (page) => {
      await expect(page.getByText("Z.AI", { exact: true })).toBeVisible();
      await expect(page.getByText("OpenRouter", { exact: true })).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-key-entry",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("Z.AI", { exact: true }).click();
    },
    settle: async (page) => {
      await expect(
        page.getByPlaceholder("Z.AI subscription key"),
      ).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-oauth",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("Claude", { exact: true }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("sign in to claude")).toBeVisible();
      await expect(page.getByPlaceholder("paste code here")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-oauth-openai",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("ChatGPT", { exact: true }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("sign in to ChatGPT")).toBeVisible();
      await expect(page.getByText("WDJB-MJHT")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-key-kimi",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("Kimi Code", { exact: true }).click();
    },
    settle: async (page) => {
      await expect(
        page.getByPlaceholder("Kimi Code subscription key"),
      ).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-model",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("OpenRouter", { exact: true }).click();
      await page.getByPlaceholder("sk-or-v1-...").fill("sk-or-v1-visual");
      await page.getByRole("button", { name: "next" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("Claude Sonnet 5")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-model-loading",
    hang: "openrouter-models",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("OpenRouter", { exact: true }).click();
      await page.getByPlaceholder("sk-or-v1-...").fill("sk-or-v1-visual");
      await page.getByRole("button", { name: "next" }).click();
    },
    settle: async (page) => {
      await expect(
        page.locator('[data-slot="skeleton"]').first(),
      ).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-model-claude",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("Claude", { exact: true }).click();
      await page.getByPlaceholder("paste code here").fill("visual-code");
      await page.getByRole("button", { name: "continue" }).click();
      await page.getByRole("button", { name: "more models" }).click();
    },
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "Opus", exact: true }),
      ).toBeVisible();
      await expect(page.getByText("Claude Opus 5")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-model-claude-collapsed",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("Claude", { exact: true }).click();
      await page.getByPlaceholder("paste code here").fill("visual-code");
      await page.getByRole("button", { name: "continue" }).click();
    },
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "more models" }),
      ).toBeVisible();
      await expect(page.getByText("Claude Opus 5")).toBeHidden();
    },
  },
  {
    ...defaults,
    id: "provider-model-zai",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("Z.AI", { exact: true }).click();
      await page
        .getByPlaceholder("Z.AI subscription key")
        .fill("visual-zai-key");
      await page.getByRole("button", { name: "next" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("GLM 5 Turbo")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-model-kimi",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("Kimi Code", { exact: true }).click();
      await page
        .getByPlaceholder("Kimi Code subscription key")
        .fill("visual-kimi-key");
      await page.getByRole("button", { name: "next" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("Coding Highspeed")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "provider-model-openai",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await page.getByText("ChatGPT", { exact: true }).click();
      await page.getByRole("button", { name: "continue" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("GPT 5.6 Terra")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "personality-default",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await crossProvider(page);
      await expect(page.getByText("pick a vibe")).toBeVisible();
    },
    settle: async (page) => {
      await expect(page.getByRole("button", { name: /dry/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    },
  },
  {
    ...defaults,
    id: "personality-selected",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await crossProvider(page);
      await page.getByRole("button", { name: /chill/ }).click();
    },
    settle: async (page) => {
      await expect(page.getByRole("button", { name: /chill/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    },
  },
  {
    ...defaults,
    id: "creating-pulling",
    deltas: [agentDelta(AGENT, startingAgent("pulling"))],
    drive: toCreating,
    settle: async (page) => {
      await expect(
        page.getByText("downloading the agent image..."),
      ).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "creating-starting",
    deltas: [agentDelta(AGENT, startingAgent("starting"))],
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("starting up...")).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "creating-failed",
    createResponse: { status: 500, body: { error: "gateway ran out of disk" } },
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("gateway ran out of disk")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "try again" }),
      ).toBeVisible();
    },
  },
  {
    ...defaults,
    id: "done",
    agentStatus: "alive",
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText(`${AGENT} is ready`)).toBeVisible();
      await expect(page.getByRole("button", { name: "say hi" })).toBeVisible();
    },
  },
  // Settings surfaces, kept out of the onboarding section: the change-model
  // dialog each fixed-catalog provider shows in AgentSettings.
  settingsModelScenario("settings-model-zai", "zai", "glm-5.2", "GLM 5 Turbo"),
  settingsModelScenario(
    "settings-model-kimi",
    "kimi",
    "kimi-for-coding",
    "Coding Highspeed",
  ),
  settingsModelScenario(
    "settings-model-openai",
    "openai",
    "gpt-5.6-sol",
    "GPT 5.6 Terra",
  ),
];
