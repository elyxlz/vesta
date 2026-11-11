import type { SettingDef } from "../api/voice";
import type { OrbMotion } from "../orb/orb";

// Where a conversation stands for the UI: "starting" while the microphone and the transcription
// socket come up, "live" once both are. The panel opens only when live, so a start that fails
// (a denied mic, an unreachable service) never flashes it open and shut.
export type ConversationStage = "starting" | "live" | null;

export function conversationStage(input: {
  recordingMode: "dictation" | "conversation" | null;
  listening: boolean;
}): ConversationStage {
  if (input.recordingMode !== "conversation") return null;
  return input.listening ? "live" : "starting";
}

interface ConversationInput {
  listening: boolean;
  micMuted: boolean;
  speaking: boolean;
  // The engine waits for the wake phrase.
  wakeWaiting: boolean;
}

// What the conversation panel says between turns, in priority order: a session still dialing,
// the agent talking, a muted mic, the agent thinking, the wake phrase not said yet, else
// listening.
export type ConversationPhase =
  "connecting" | "speaking" | "muted" | "thinking" | "waiting" | "listening";

export function conversationPhase(
  input: ConversationInput & { thinking: boolean },
): ConversationPhase {
  if (!input.listening) return "connecting";
  if (input.speaking) return "speaking";
  if (input.micMuted) return "muted";
  if (input.thinking) return "thinking";
  if (input.wakeWaiting) return "waiting";
  return "listening";
}

export function conversationPhaseLabel(
  phase: ConversationPhase,
  wakePhrase: string | null,
): string {
  if (phase === "connecting") return "connecting…";
  if (phase === "waiting")
    return wakePhrase ? `say “${wakePhrase}”` : "waiting for the wake word";
  return phase;
}

// The status decides the orb's look; the voice phase only decides its motion. A muted mic or a
// still-dialing session holds the orb still rather than pretending to listen.
export function conversationMotion(
  input: ConversationInput,
): OrbMotion | undefined {
  if (input.speaking) return "talking";
  if (!input.listening || input.micMuted) return undefined;
  return input.wakeWaiting ? "waiting" : "listening";
}

// The behavior a client sets to turn its own wake word on or off.
export const WAKE_WORD_SETTING = "wake_word";
const WAKE_PHRASE_SETTING = "wake_word_phrase";

// The wake word of this client, read from its behaviors: null for a voice service with no
// wake word, which shows no toggle.
export function wakeWordBehavior(
  settings: SettingDef[] | undefined,
): { on: boolean; phrase: string | null } | null {
  const toggle = settings?.find((s) => s.key === WAKE_WORD_SETTING);
  if (!toggle) return null;
  const phrase = settings?.find((s) => s.key === WAKE_PHRASE_SETTING)?.value;
  return {
    on: toggle.value === true,
    phrase: typeof phrase === "string" && phrase ? phrase : null,
  };
}

// The live transcript split so the freshest word can be set bold: everything up to and
// including the last space, then the last word.
export function splitSpokenTail(transcript: string): {
  head: string;
  tail: string;
} {
  const lastSpace = transcript.lastIndexOf(" ");
  if (lastSpace === -1) return { head: "", tail: transcript };
  return {
    head: transcript.slice(0, lastSpace + 1),
    tail: transcript.slice(lastSpace + 1),
  };
}
