import type { Page } from "@playwright/test";
import type { VoiceBehaviors, VoiceStatus } from "@vesta/core";
import { CONVERSATION, chatRoutes } from "../harness/chat-fixtures";
import { AGENT, type RouteFixture } from "../harness/http-fixtures";
import type { Scenario } from "../harness/scenario-state";
import { agentNode } from "../harness/sync-fixtures";

const ON: VoiceStatus = {
  configured: true,
  provider: "deepgram",
  connected: ["deepgram"],
  enabled: true,
  settings: [],
};

const BEHAVIORS: VoiceBehaviors = {
  settings: [
    {
      key: "barge_in",
      type: "bool",
      label: "interrupt by voice",
      value: true,
    },
    { key: "wake_word", type: "bool", label: "wake word", value: true },
    {
      key: "wake_word_phrase",
      type: "text",
      label: "wake phrase",
      value: "hey aria",
    },
  ],
};

const TRANSCRIPT = "Also book the room for Thursday";

function voiceRoute(path: string, json: unknown): RouteFixture {
  return { path: `/agents/${AGENT}/voice${path}`, json };
}

// A microphone that gives silence, so a conversation starts with no device and no prompt.
async function silentMicrophone(page: Page): Promise<void> {
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = () =>
      Promise.resolve(new AudioContext().createMediaStreamDestination().stream);
  });
}

// The voice engine as the panel reads it: it accepts the session, then either waits for the
// wake phrase or hears the user's words.
async function voiceEngine(page: Page, waiting: boolean): Promise<void> {
  await page.routeWebSocket(/\/voice\/voice\/session/, (ws) => {
    ws.onMessage((message) => {
      if (typeof message !== "string" || !message.includes("start_session"))
        return;
      ws.send(JSON.stringify({ type: "state", value: "listening" }));
      if (waiting)
        ws.send(JSON.stringify({ type: "wake_listening", value: true }));
      else ws.send(JSON.stringify({ type: "transcript", text: TRANSCRIPT }));
    });
  });
}

function conversation(waiting: boolean): Scenario {
  return {
    state: {
      route: `/agent/${AGENT}/chat`,
      sync: {
        agents: {
          [AGENT]: agentNode("alive", {
            services: { voice: { port: 7000, rev: 1, public: false } },
          }),
        },
      },
      routes: [
        ...chatRoutes(AGENT, { events: CONVERSATION }),
        voiceRoute("/stt/status", ON),
        voiceRoute("/tts/status", ON),
        voiceRoute("/judge/status", { configured: false, provider: null }),
        voiceRoute("/behavior/status", BEHAVIORS),
      ],
      chatSocket: { agent: AGENT, events: [] },
    },
    drive: async (page) => {
      await silentMicrophone(page);
      await voiceEngine(page, waiting);
      await page.getByRole("button", { name: "start conversation" }).click();
      await page
        .getByRole("button", { name: "end conversation" })
        .first()
        .waitFor();
      await page
        .getByText(waiting ? "say “hey aria”" : "Thursday", { exact: false })
        .filter({ visible: true })
        .first()
        .waitFor();
    },
  };
}

export const VOICE: Record<string, Scenario> = {
  "chat-voice-conversation": conversation(false),
  "chat-voice-conversation-wake": conversation(true),
};
