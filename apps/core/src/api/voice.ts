import type { ClientKind } from "../protocol/frames";
import { ApiError, jsonInit, type HttpClient } from "../transport/http";
import { agentPath } from "./agents";

// A role of the voice service: the mic, the voice, and the judge that decides who the user's
// words are for while a reply plays.
export type VoiceDomain = "stt" | "tts" | "judge";

// A dynamic setting the voice service describes for its settings card; `config` nests the settings
// of a chosen option (a provider's own knobs).
export interface SettingDef {
  key: string;
  type: "bool" | "number" | "select" | "text";
  label: string;
  description?: string;
  value: unknown;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  config?: SettingDef[];
  config_label?: string;
  options?: {
    value: string;
    label: string;
    description?: string;
    preview?: string;
    custom?: boolean;
  }[];
}

export interface VoiceStatus {
  configured: boolean;
  provider: string | null;
  // Every provider connected to this role, the selected one included.
  connected?: string[];
  enabled?: boolean;
  settings?: SettingDef[];
}

// The behaviors: values that change how a voice session acts, whichever provider is selected.
// Each client kind reads and sets its own values, which start as the shared ones. They use the
// settings format of the providers.
export interface VoiceBehaviors {
  settings: SettingDef[];
}

// An amount of a provider's account. The unit is "usd", "hours", "credits", or one the
// provider names.
export interface VoiceAmount {
  amount: number;
  unit: string;
}

// What the account of a role's provider used this month and has left, in one shape for every
// provider. Null where the provider does not say.
export interface VoiceUsage {
  used: VoiceAmount | null;
  left: VoiceAmount | null;
}

function voicePath(name: string, suffix: string): string {
  return agentPath(name, `/voice/${suffix}`);
}

// LEGACY(remove-when: every agent in the fleet has run the 2026-10-voice-engine migration):
// a voice service from before that migration lists `interrupt_tts` among the STT settings.
// The barge_in behavior holds that choice, so the setting is dropped here and no client
// shows a switch that nothing reads.
async function voiceStatus(
  http: HttpClient,
  path: string,
  init: RequestInit,
): Promise<VoiceStatus> {
  const status = await http.json<VoiceStatus>(path, init);
  if (!status.settings) return status;
  return {
    ...status,
    settings: status.settings.filter((s) => s.key !== "interrupt_tts"),
  };
}

// The voice engine socket (GET .../voice/voice/session), one for each voice session; dialed
// with the token in the query.
export function voiceSessionPath(name: string): string {
  return voicePath(name, "voice/session");
}

// The audio of one play of a session. The engine names it as a path on the voice service
// (`/voice/play/<token>`), and a media element fetches it with the token in the query.
export function voicePlayPath(name: string, enginePath: string): string {
  return voicePath(name, enginePath.replace(/^\//, ""));
}

// The streamed speech a media element plays (GET .../voice/tts/stream/{id}?token=...). A media
// element carries no Authorization header, so the text is registered first via prepareSpeech.
export function ttsStreamPath(name: string, id: string): string {
  return voicePath(name, `tts/stream/${encodeURIComponent(id)}`);
}

// The play formats the speaker decodes. The voice service picks the best one its TTS provider
// makes and owns the bitrate, so a change of quality needs no app release.
export function playbackFormats(playsOggOpus: boolean): string[] {
  return [...(playsOggOpus ? ["opus_48000"] : []), "mp3_44100", "mp3_22050"];
}

// The query of a streamed speech url: the formats its player decodes.
export function ttsStreamQuery(playsOggOpus: boolean): URLSearchParams {
  return new URLSearchParams({
    formats: playbackFormats(playsOggOpus).join(","),
  });
}

export async function fetchVoiceStatus(
  http: HttpClient,
  name: string,
  domain: VoiceDomain,
  signal?: AbortSignal,
): Promise<VoiceStatus> {
  return voiceStatus(http, voicePath(name, `${domain}/status`), { signal });
}

const NOT_FOUND = 404;

// A voice service with no judge or behavior routes answers 404, which reads as none. Every
// other failure throws, so a transient error never hides a card.
async function noneWhenMissing<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (error) {
    if (error instanceof ApiError && error.status === NOT_FOUND) return null;
    throw error;
  }
}

// What the voice settings show. The judge and the behaviors are null for an agent whose voice
// service has no such route.
export interface VoiceSettingsData {
  stt: VoiceStatus;
  tts: VoiceStatus;
  judge: VoiceStatus | null;
  behaviors: VoiceBehaviors | null;
}

export async function fetchVoiceSettings(
  http: HttpClient,
  name: string,
  client: ClientKind,
  signal?: AbortSignal,
): Promise<VoiceSettingsData> {
  const query = new URLSearchParams({ client });
  const [stt, tts, judge, behaviors] = await Promise.all([
    fetchVoiceStatus(http, name, "stt", signal),
    fetchVoiceStatus(http, name, "tts", signal),
    noneWhenMissing(fetchVoiceStatus(http, name, "judge", signal)),
    noneWhenMissing(
      http.json<VoiceBehaviors>(
        voicePath(name, `behavior/status?${query.toString()}`),
        { signal },
      ),
    ),
  ]);
  return { stt, tts, judge, behaviors };
}

export async function setVoiceBehavior(
  http: HttpClient,
  name: string,
  client: ClientKind,
  key: string,
  value: unknown,
): Promise<VoiceBehaviors> {
  return http.json<VoiceBehaviors>(
    voicePath(name, "behavior/set"),
    jsonInit("POST", { key, value, client }),
  );
}

// The judge has no account to show.
export async function fetchVoiceUsage(
  http: HttpClient,
  name: string,
  domain: "stt" | "tts",
): Promise<VoiceUsage> {
  return http.json<VoiceUsage>(voicePath(name, `${domain}/usage`));
}

export async function setVoiceEnabled(
  http: HttpClient,
  name: string,
  domain: VoiceDomain,
  value: boolean,
): Promise<VoiceStatus> {
  return voiceStatus(
    http,
    voicePath(name, `${domain}/set-enabled`),
    jsonInit("POST", { value }),
  );
}

// Switches a role to one of its connected providers. Each provider keeps its own key and
// settings, so the answer is the status of the role under the new provider.
export async function selectVoiceProvider(
  http: HttpClient,
  name: string,
  domain: VoiceDomain,
  provider: string,
): Promise<VoiceStatus> {
  return voiceStatus(
    http,
    voicePath(name, `${domain}/use`),
    jsonInit("POST", { provider }),
  );
}

export async function setVoiceSetting(
  http: HttpClient,
  name: string,
  domain: VoiceDomain,
  key: string,
  value: unknown,
): Promise<VoiceStatus> {
  return voiceStatus(
    http,
    voicePath(name, `${domain}/set`),
    jsonInit("POST", { key, value }),
  );
}

export async function prepareSpeech(
  http: HttpClient,
  name: string,
  text: string,
  signal?: AbortSignal,
): Promise<string> {
  const response = await http.json<{ id: string }>(
    voicePath(name, "tts/prepare"),
    { ...jsonInit("POST", { text }), signal },
  );
  return response.id;
}
