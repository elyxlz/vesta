import {
  agentHoldKey,
  initialChatState,
  seedTail,
  type ChatAttachment,
  type ChatMessage,
  type ChatState,
  type DraftAttachment,
} from "@vesta/core";
import { agentHolds } from "../../src/holds/agent-holds";
import { connectionKeyOf } from "../../src/session/session-model";
import { visualSwitch } from "./launch-query";
import { visualConnection } from "./session-provider";

export * from "../../src/holds/agent-holds";

// visualChat picks aria's transcript: the default short exchange, `delivery`
// (a bubble still sending and one the gateway refused), `errors` (the snag and
// rate-limit lines), `markdown` (a rich reply), or `long` (days of history, for
// the scroll-to-bottom control and date headers).
const chatVariant = visualSwitch("visualChat");
const conversation: ChatMessage[] = [
  {
    id: 101,
    type: "user",
    text: "What should I focus on before tomorrow's product review?",
    ts: "2026-08-01T09:18:00.000Z",
  },
  {
    id: 102,
    type: "chat",
    text: "The onboarding polish and mobile QA gaps are the two items most likely to unblock the review.",
    ts: "2026-08-01T09:18:14.000Z",
  },
  {
    id: 103,
    type: "user",
    text: "Turn that into a short checklist.",
    ts: "2026-08-01T09:19:00.000Z",
  },
  {
    id: 104,
    type: "chat",
    text: "Done. I prioritized the visual regressions first, then the demo notes and follow-ups.",
    ts: "2026-08-01T09:19:11.000Z",
  },
  {
    id: 105,
    type: "user",
    text: "> Done. I prioritized the visual regressions first, then the demo notes and follow-ups.\n\nPerfect, let's start with the visual regressions.",
    ts: "2026-08-01T09:20:00.000Z",
  },
];
const deliveryTail: ChatMessage[] = [
  {
    type: "user",
    text: "Also book the room for Thursday.",
    ts: "2026-08-01T09:21:00.000Z",
    intent_id: "visual-sending",
    send_state: "sending",
  },
  {
    type: "user",
    text: "And send the agenda to the team.",
    ts: "2026-08-01T09:21:30.000Z",
    intent_id: "visual-failed",
    send_state: "failed",
  },
];
const errorTail: ChatMessage[] = [
  {
    id: 106,
    type: "user",
    text: "Summarise the launch thread.",
    ts: "2026-08-01T09:22:00.000Z",
  },
  {
    id: 107,
    type: "error",
    text: "turn failed",
    ts: "2026-08-01T09:22:05.000Z",
  },
  {
    id: 108,
    type: "rate_limited",
    text: "rate limited",
    window: "5h",
    resets_at: Date.UTC(2026, 7, 1, 11, 0),
    ts: "2026-08-01T09:22:06.000Z",
  },
];
const markdownTail: ChatMessage[] = [
  {
    id: 109,
    type: "user",
    text: "How do I rotate the gateway key?",
    ts: "2026-08-01T09:23:00.000Z",
  },
  {
    id: 110,
    type: "chat",
    text: [
      "## Rotating the key",
      "",
      "1. Open **Settings**, then **Gateway**.",
      "2. Run the rotate command:",
      "",
      "```bash",
      "vestad rotate-key --confirm",
      "```",
      "",
      "- Every client needs the new connect link.",
      "- Old links stop working at once.",
      "",
      "Details in the [gateway guide](https://vesta.run/docs/gateway).",
    ].join("\n"),
    ts: "2026-08-01T09:23:20.000Z",
  },
];
const longHistory: ChatMessage[] = Array.from({ length: 40 }, (_, index) => {
  const day = 25 + Math.floor(index / 8);
  const minute = (index % 8) * 7;
  const user = index % 2 === 0;
  return {
    id: 200 + index,
    type: user ? "user" : "chat",
    text: user
      ? `Status check ${index / 2 + 1}: anything new on the launch?`
      : "Nothing blocking. Two reviews merged, one waiting on design.",
    ts: new Date(Date.UTC(2026, 6, day, 9, minute)).toISOString(),
  };
});
// `attachments` shows a bubble of every kind; `attachments-degraded` the removed (410) and
// broken tiles. The ids key into the visual authed-media-uri fixture and the session fixture's
// HEAD answers.
const PHOTO: ChatAttachment = {
  id: "att-photo",
  name: "sunset.jpg",
  mime: "image/jpeg",
  size: 2_465_792,
  width: 640,
  height: 480,
};
const attachmentsTail: ChatMessage[] = [
  {
    id: 120,
    type: "user",
    text: "Here's the terrace at golden hour.",
    ts: "2026-08-01T09:24:00.000Z",
    attachments: [PHOTO],
  },
  {
    id: 121,
    type: "user",
    text: "",
    ts: "2026-08-01T09:24:30.000Z",
    attachments: [
      {
        id: "att-video",
        name: "walkthrough.mp4",
        mime: "video/mp4",
        size: 8_388_608,
        width: 320,
        height: 240,
        duration_secs: 1,
      },
    ],
  },
  {
    id: 122,
    type: "chat",
    text: "Saved both. Here's the report you asked for, plus the voice note.",
    ts: "2026-08-01T09:25:00.000Z",
    attachments: [
      {
        id: "att-file",
        name: "quarterly-report.pdf",
        mime: "application/pdf",
        size: 1_264_640,
      },
      {
        id: "att-audio",
        name: "voice-note.wav",
        mime: "audio/wav",
        size: 16_044,
        duration_secs: 1,
      },
    ],
  },
];
const degradedTail: ChatMessage[] = [
  {
    id: 123,
    type: "user",
    text: "",
    ts: "2026-08-01T09:26:00.000Z",
    attachments: [
      {
        id: "att-removed",
        name: "old-scan.jpg",
        mime: "image/jpeg",
        size: 1_048_576,
        width: 640,
        height: 480,
      },
    ],
  },
  {
    id: 124,
    type: "chat",
    text: "That one aged out of my storage.",
    ts: "2026-08-01T09:26:10.000Z",
    attachments: [
      {
        id: "att-broken",
        name: "unreachable.jpg",
        mime: "image/jpeg",
        size: 524_288,
        width: 640,
        height: 480,
      },
    ],
  },
];
const events: ChatMessage[] =
  chatVariant === "delivery"
    ? [...conversation, ...deliveryTail]
    : chatVariant === "errors"
      ? [...conversation, ...errorTail]
      : chatVariant === "markdown"
        ? [...conversation, ...markdownTail]
        : chatVariant === "long"
          ? [...longHistory, ...conversation]
          : chatVariant === "attachments"
            ? [...conversation, ...attachmentsTail]
            : chatVariant === "attachments-degraded"
              ? [...conversation, ...degradedTail]
              : conversation;
const chatState: ChatState = seedTail(initialChatState(), {
  events,
  cursor: null,
});

// visualAttachments seeds aria's composer chips: `chips` (two uploaded, ready to send, with the
// totals line), `uploading` (one mid-progress), `waiting` (one parked offline, one failed).
const attachmentsVariant = visualSwitch("visualAttachments");
const uploadedDraft = (
  localId: string,
  attachment: ChatAttachment,
): DraftAttachment => ({
  localId,
  name: attachment.name,
  mime: attachment.mime,
  size: attachment.size,
  progress: 1,
  status: "uploaded",
  attachment,
});
const REPORT: ChatAttachment = {
  id: "att-file",
  name: "quarterly-report.pdf",
  mime: "application/pdf",
  size: 1_264_640,
};
const chipDrafts: DraftAttachment[] =
  attachmentsVariant === "chips"
    ? [uploadedDraft("visual-d1", PHOTO), uploadedDraft("visual-d2", REPORT)]
    : attachmentsVariant === "uploading"
      ? [
          uploadedDraft("visual-d1", PHOTO),
          {
            localId: "visual-d3",
            name: "walkthrough.mp4",
            mime: "video/mp4",
            size: 8_388_608,
            progress: 0.55,
            status: "uploading",
          },
        ]
      : attachmentsVariant === "waiting"
        ? [
            {
              localId: "visual-d4",
              name: "walkthrough.mp4",
              mime: "video/mp4",
              size: 8_388_608,
              progress: 0.2,
              status: "waiting",
            },
            {
              localId: "visual-d5",
              name: "quarterly-report.pdf",
              mime: "application/pdf",
              size: 1_264_640,
              progress: 0,
              status: "error",
              error: "failed",
            },
          ]
        : [];

const connectionKey = connectionKeyOf(visualConnection) ?? "";
agentHolds.chat.persist(agentHoldKey("aria", connectionKey), chatState);
if (chipDrafts.length > 0)
  agentHolds.attachments.persist(
    agentHoldKey("aria", connectionKey),
    chipDrafts,
  );
// nova has history loaded and no messages, so opening nova renders the empty-chat state.
agentHolds.chat.persist(
  agentHoldKey("nova", connectionKey),
  seedTail(initialChatState(), { events: [], cursor: null }),
);
