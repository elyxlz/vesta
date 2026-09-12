import type { Page } from "@playwright/test";
import { chatRoutes } from "../harness/chat-fixtures";
import { AGENT } from "../harness/http-fixtures";
import {
  FIXED_TIME,
  noDrive,
  type Scenario,
  type ScenarioState,
} from "../harness/scenario-state";
import { agentNode, directRooms } from "../harness/sync-fixtures";
import { GROUP_HISTORY, GROUP_ROOM } from "./chat";

const CHATS_ROUTE = "/chats";

// The inbox fixture: the agents' own chats plus a group and a pair, each with the time of its last
// message. The group is the one the chat drives carry history for, so selecting it renders bubbles.
const CHATS_AGENTS = Object.fromEntries(
  [AGENT, "atlas", "iris"].map((name) => [name, agentNode()] as const),
);
const CHATS_ROOMS = [
  ...directRooms(CHATS_AGENTS).map((room, index) => ({
    ...room,
    lastMessageAt: FIXED_TIME.getTime() / 1000 - (index + 1) * 900,
  })),
  {
    id: GROUP_ROOM,
    name: "lisbon trip",
    agents: [AGENT, "atlas"],
    createdAt: 1_755_400_000,
    lastMessageAt: FIXED_TIME.getTime() / 1000 - 4 * 3600,
  },
  {
    id: "peer-research",
    name: null,
    agents: ["atlas", "iris"],
    createdAt: 1_755_300_000,
    lastMessageAt: FIXED_TIME.getTime() / 1000 - 3 * 86400,
  },
];

function chatsState(route = CHATS_ROUTE): ScenarioState {
  return {
    route,
    sync: { agents: CHATS_AGENTS, rooms: CHATS_ROOMS },
  };
}

async function openNewGroup(page: Page): Promise<void> {
  await page.getByRole("button", { name: "new group" }).click();
  await page.getByLabel("group name").fill("weekend plans");
  await page.getByRole("checkbox").first().click();
}

export const CHATS: Record<string, Scenario> = {
  "chats-empty": { state: chatsState(), drive: noDrive },
  "chats-selected": {
    state: {
      ...chatsState(`${CHATS_ROUTE}/${GROUP_ROOM}`),
      routes: chatRoutes(GROUP_ROOM, { events: GROUP_HISTORY }),
      chatSocket: { events: [] },
    },
    drive: noDrive,
  },
  "chats-narrow": { state: chatsState(), drive: noDrive },
  "new-room-dialog": { state: chatsState(), drive: openNewGroup },
};
