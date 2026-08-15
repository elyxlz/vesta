import { expect, type Page } from "@playwright/test";
import type { AgentStatus, Delta } from "@vesta/core";
import { agentDelta, startingAgent } from "./harness/sync-fixtures";
import { AGENT } from "./harness/http-fixtures";

export interface Scenario {
  id: string;
  agentStatus: AgentStatus;
  createResponse: { status: number; body: { error: string } } | null;
  deltas: Delta[];
  drive: (page: Page) => Promise<void>;
  settle: (page: Page) => Promise<void>;
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
}

async function toCreating(page: Page): Promise<void> {
  await fillName(page, AGENT);
  await submitName(page);
  await crossProvider(page);
  await expect(page.getByText("pick a vibe")).toBeVisible();
  await page.getByRole("button", { name: "continue" }).click();
}

const defaults = {
  agentStatus: "starting" as AgentStatus,
  createResponse: null,
  deltas: [] as Delta[],
};

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
    id: "name-hint",
    drive: async (page) => {
      await fillName(page, "My Agent!");
    },
    settle: async (page) => {
      await expect(page.getByText('will be called "my-agent"')).toBeVisible();
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
    id: "personality-selected",
    drive: async (page) => {
      await fillName(page, AGENT);
      await submitName(page);
      await crossProvider(page);
      await page.getByRole("button", { name: /night owl/ }).click();
    },
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: /night owl/ }),
      ).toHaveAttribute("aria-pressed", "true");
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
];
