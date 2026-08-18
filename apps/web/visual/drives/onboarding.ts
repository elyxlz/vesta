import { expect, type Page } from "@playwright/test";
import {
  AGENT,
  providerRoute,
  type ProviderInfoFixture,
  type RouteFixture,
} from "../harness/http-fixtures";
import type { Scenario } from "../harness/scenario-state";
import {
  agentDelta,
  aliveAgentNode,
  startingAgent,
} from "../harness/sync-fixtures";

function createFailure(status: number, error: string): RouteFixture {
  return { path: "/agents", method: "POST", status, json: { error } };
}
function keyedProvider(
  kind: ProviderInfoFixture["kind"],
  model: string,
): ProviderInfoFixture {
  return {
    kind,
    model,
    resolved_model: model,
    max_context_tokens: 131072,
    authed: true,
    plan: null,
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
async function toProvider(page: Page, provider: string): Promise<void> {
  await fillName(page, AGENT);
  await submitName(page);
  await page.getByText(provider, { exact: true }).click();
}
async function toKeyedModel(
  page: Page,
  provider: string,
  placeholder: string,
  key: string,
): Promise<void> {
  await toProvider(page, provider);
  await page.getByPlaceholder(placeholder).fill(key);
  await page.getByRole("button", { name: "next" }).click();
}
async function toClaudeModel(page: Page): Promise<void> {
  await toProvider(page, "Claude");
  await page.getByPlaceholder("paste code here").fill("visual-code");
  await page.getByRole("button", { name: "continue" }).click();
}
function settingsModel(
  provider: ProviderInfoFixture,
  visibleLabel: string,
): Scenario {
  return {
    state: {
      route: `/agent/${AGENT}/settings`,
      sync: { agents: { [AGENT]: aliveAgentNode() } },
      routes: [providerRoute(provider)],
    },
    drive: async (page) => {
      await page.getByRole("button", { name: "change model" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText(visibleLabel)).toBeVisible();
    },
  };
}

export const ONBOARDING: Record<string, Scenario> = {
  "name-empty": {
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(page.getByPlaceholder("name your agent")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "continue" }),
      ).toBeDisabled();
    },
  },
  "name-valid": {
    drive: (page) => fillName(page, "luna"),
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "continue" }),
      ).toBeEnabled();
    },
  },
  "name-rejected": {
    state: { routes: [createFailure(409, "name already taken")] },
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("name already taken")).toBeVisible();
      await expect(page.getByPlaceholder("name your agent")).toBeVisible();
    },
  },
  "provider-choice": {
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
    },
    settle: async (page) => {
      await expect(page.getByText("Z.AI", { exact: true })).toBeVisible();
      await expect(page.getByText("OpenRouter", { exact: true })).toBeVisible();
    },
  },
  "provider-key-entry": {
    drive: (page) => toProvider(page, "Z.AI"),
    settle: async (page) => {
      await expect(
        page.getByPlaceholder("Z.AI subscription key"),
      ).toBeVisible();
    },
  },
  "provider-oauth": {
    drive: (page) => toProvider(page, "Claude"),
    settle: async (page) => {
      await expect(page.getByText("sign in to claude")).toBeVisible();
      await expect(page.getByPlaceholder("paste code here")).toBeVisible();
    },
  },
  "provider-oauth-openai": {
    drive: (page) => toProvider(page, "ChatGPT"),
    settle: async (page) => {
      await expect(page.getByText("sign in to ChatGPT")).toBeVisible();
      await expect(page.getByText("WDJB-MJHT")).toBeVisible();
    },
  },
  "provider-key-kimi": {
    drive: (page) => toProvider(page, "Kimi Code"),
    settle: async (page) => {
      await expect(
        page.getByPlaceholder("Kimi Code subscription key"),
      ).toBeVisible();
    },
  },
  "provider-model": {
    drive: (page) =>
      toKeyedModel(page, "OpenRouter", "sk-or-v1-...", "sk-or-v1-visual"),
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("Claude Sonnet 5")).toBeVisible();
    },
  },
  "provider-model-loading": {
    state: {
      routes: [{ path: "/providers/openrouter/models/top", hang: true }],
    },
    drive: (page) =>
      toKeyedModel(page, "OpenRouter", "sk-or-v1-...", "sk-or-v1-visual"),
    settle: async (page) => {
      await expect(
        page.locator('[data-slot="skeleton"]').first(),
      ).toBeVisible();
    },
  },
  "provider-model-claude": {
    drive: async (page) => {
      await toClaudeModel(page);
      await page.getByRole("button", { name: "more models" }).click();
    },
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "Opus", exact: true }),
      ).toBeVisible();
      await expect(page.getByText("Claude Opus 5")).toBeVisible();
    },
  },
  "provider-model-claude-collapsed": {
    drive: toClaudeModel,
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "more models" }),
      ).toBeVisible();
      await expect(page.getByText("Claude Opus 5")).toBeHidden();
    },
  },
  "provider-model-zai": {
    drive: (page) =>
      toKeyedModel(page, "Z.AI", "Z.AI subscription key", "visual-zai-key"),
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("GLM 5 Turbo")).toBeVisible();
    },
  },
  "provider-model-kimi": {
    drive: (page) =>
      toKeyedModel(
        page,
        "Kimi Code",
        "Kimi Code subscription key",
        "visual-kimi-key",
      ),
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("Coding Highspeed")).toBeVisible();
    },
  },
  "provider-model-openai": {
    drive: async (page) => {
      await toProvider(page, "ChatGPT");
      await page.getByRole("button", { name: "continue" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("pick a model")).toBeVisible();
      await expect(page.getByText("GPT 5.6 Terra")).toBeVisible();
    },
  },
  "personality-default": {
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
  "personality-selected": {
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
  "creating-pulling": {
    state: {
      sync: { deltas: [agentDelta(AGENT, startingAgent("pulling"))] },
    },
    drive: toCreating,
    settle: async (page) => {
      await expect(
        page.getByText("downloading the agent image..."),
      ).toBeVisible();
    },
  },
  "creating-starting": {
    state: {
      sync: { deltas: [agentDelta(AGENT, startingAgent("starting"))] },
    },
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("starting up...")).toBeVisible();
    },
  },
  "creating-failed": {
    state: { routes: [createFailure(500, "gateway ran out of disk")] },
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText("gateway ran out of disk")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "try again" }),
      ).toBeVisible();
    },
  },
  done: {
    state: {
      routes: [
        { path: `/agents/${AGENT}`, method: "GET", json: { status: "alive" } },
      ],
    },
    drive: toCreating,
    settle: async (page) => {
      await expect(page.getByText(`${AGENT} is ready`)).toBeVisible();
      await expect(page.getByRole("button", { name: "say hi" })).toBeVisible();
    },
  },
  "settings-model-zai": settingsModel(
    keyedProvider("zai", "glm-5.2"),
    "GLM 5 Turbo",
  ),
  "settings-model-kimi": settingsModel(
    keyedProvider("kimi", "kimi-for-coding"),
    "Coding Highspeed",
  ),
  "settings-model-openai": settingsModel(
    keyedProvider("openai", "gpt-5.6-sol"),
    "GPT 5.6 Terra",
  ),
};
