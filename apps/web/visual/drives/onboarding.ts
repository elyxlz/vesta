import { type Page } from "@playwright/test";
import {
  AGENT,
  providerRoute,
  type ProviderInfoFixture,
  type RouteFixture,
} from "../harness/http-fixtures";
import type { Scenario } from "../harness/scenario-state";
import {
  agentDelta,
  agentNode,
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
async function startCreating(page: Page): Promise<void> {
  await fillName(page, AGENT);
  await submitName(page);
}
async function toApplying(page: Page): Promise<void> {
  await fillName(page, AGENT);
  await submitName(page);
  await crossProvider(page);
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
function settingsModel(provider: ProviderInfoFixture): Scenario {
  return {
    state: {
      route: `/agent/${AGENT}/settings`,
      sync: { agents: { [AGENT]: aliveAgentNode() } },
      routes: [providerRoute(provider)],
    },
    drive: async (page) => {
      await page.getByRole("tab", { name: "provider", exact: true }).click();
      await page.getByRole("button", { name: "change model" }).click();
    },
  };
}

export const ONBOARDING: Record<string, Scenario> = {
  "name-empty": {
    drive: () => Promise.resolve(),
  },
  "name-valid": {
    drive: (page) => fillName(page, "luna"),
  },
  "name-rejected": {
    state: { routes: [createFailure(409, "name already taken")] },
    drive: startCreating,
  },
  "provider-choice": {
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
    },
  },
  "provider-key-entry": {
    drive: (page) => toProvider(page, "Z.AI"),
  },
  "provider-oauth": {
    drive: (page) => toProvider(page, "Claude"),
  },
  "provider-oauth-openai": {
    drive: (page) => toProvider(page, "ChatGPT"),
  },
  "provider-key-kimi": {
    drive: (page) => toProvider(page, "Kimi Code"),
  },
  "provider-model": {
    drive: (page) =>
      toKeyedModel(page, "OpenRouter", "sk-or-v1-...", "sk-or-v1-visual"),
  },
  "provider-model-loading": {
    state: {
      routes: [
        {
          path: `/agents/${AGENT}/providers/openrouter/models/top`,
          hang: true,
        },
      ],
    },
    drive: (page) =>
      toKeyedModel(page, "OpenRouter", "sk-or-v1-...", "sk-or-v1-visual"),
  },
  "provider-model-claude": {
    drive: async (page) => {
      await toClaudeModel(page);
      await page.getByRole("button", { name: "more models" }).click();
    },
  },
  "provider-model-claude-collapsed": {
    drive: toClaudeModel,
  },
  "provider-model-zai": {
    drive: (page) =>
      toKeyedModel(page, "Z.AI", "Z.AI subscription key", "visual-zai-key"),
  },
  "provider-model-kimi": {
    drive: (page) =>
      toKeyedModel(
        page,
        "Kimi Code",
        "Kimi Code subscription key",
        "visual-kimi-key",
      ),
  },
  "provider-model-openai": {
    drive: async (page) => {
      await toProvider(page, "ChatGPT");
      await page.getByRole("button", { name: "continue" }).click();
    },
  },
  "personality-default": {
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await crossProvider(page);
    },
  },
  "personality-selected": {
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await crossProvider(page);
      await page.getByRole("button", { name: /chill/ }).click();
    },
  },
  "creating-pulling": {
    state: {
      sync: { deltas: [agentDelta(AGENT, startingAgent("pulling"))] },
      routes: [
        {
          path: `/agents/${AGENT}`,
          method: "GET",
          json: { status: "starting", booting: false },
        },
      ],
    },
    drive: startCreating,
  },
  "creating-starting": {
    state: {
      sync: { deltas: [agentDelta(AGENT, startingAgent("starting"))] },
      routes: [
        {
          path: `/agents/${AGENT}`,
          method: "GET",
          json: { status: "starting", booting: false },
        },
      ],
    },
    drive: startCreating,
  },
  "creating-failed": {
    state: { routes: [createFailure(500, "gateway ran out of disk")] },
    drive: startCreating,
  },
  "applying-booting": {
    state: {
      sync: {
        agents: {
          [AGENT]: agentNode("alive", { booting: true }),
        },
      },
      routes: [
        {
          path: `/agents/${AGENT}`,
          method: "GET",
          json: { status: "unprovisioned", booting: false },
          jsonAfterRequest: {
            path: `/agents/${AGENT}/provider`,
            method: "PUT",
            json: { status: "alive", booting: true },
          },
        },
      ],
    },
    drive: toApplying,
  },
  done: {
    state: {
      routes: [
        {
          path: `/agents/${AGENT}`,
          method: "GET",
          json: { status: "unprovisioned", booting: false },
          jsonAfterRequest: {
            path: `/agents/${AGENT}/provider`,
            method: "PUT",
            json: { status: "alive", booting: false },
          },
        },
      ],
    },
    drive: toApplying,
  },
  "settings-model-zai": settingsModel(keyedProvider("zai", "glm-5.2")),
  "settings-model-kimi": settingsModel(
    keyedProvider("kimi", "kimi-for-coding"),
  ),
  "settings-model-openai": settingsModel(
    keyedProvider("openai", "gpt-5.6-sol"),
  ),
};
