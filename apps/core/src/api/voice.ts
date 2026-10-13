import { jsonInit, type HttpClient } from "../transport/http";
import { agentPath } from "./agents";

export type VoiceDomain = "stt" | "tts";

// A dynamic setting the voice service describes for its settings card; `config` nests the settings
// of a chosen option (a provider's own knobs).
export interface SettingDef {
  key: string;
  type: "bool" | "number" | "select";
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
  enabled?: boolean;
  settings?: SettingDef[];
}

// The behaviors: values that change how every voice session acts, whichever provider is
// selected. They use the settings format of the providers.
export interface VoiceBehaviors {
  settings: SettingDef[];
}

// Barge-in (the user's voice stops a spoken reply) is on unless the behavior says off, so an
// agent whose voice service reports no behaviors gets the default.
export function bargeInEnabled(behaviors: VoiceBehaviors | null): boolean {
  return behaviors?.settings.find((s) => s.key === "barge_in")?.value !== false;
}

export interface SttUsage {
  usage?: { results?: { hours?: number }[] };
  balance?: { balances?: { amount?: number; units?: string }[] };
}

export interface TtsUsage {
  usage?: { character_count?: number; character_limit?: number };
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

// The live transcription socket (GET .../voice/stt/listen); dialed with the token in the query.
export function sttListenPath(name: string): string {
  return voicePath(name, "stt/listen");
}

// The streamed speech a media element plays (GET .../voice/tts/stream/{id}?token=...). A media
// element carries no Authorization header, so the text is registered first via prepareSpeech.
export function ttsStreamPath(name: string, id: string): string {
  return voicePath(name, `tts/stream/${encodeURIComponent(id)}`);
}

export async function fetchVoiceStatus(
  http: HttpClient,
  name: string,
  domain: VoiceDomain,
  signal?: AbortSignal,
): Promise<VoiceStatus> {
  return voiceStatus(http, voicePath(name, `${domain}/status`), { signal });
}

export async function fetchVoiceBehaviors(
  http: HttpClient,
  name: string,
  signal?: AbortSignal,
): Promise<VoiceBehaviors> {
  return http.json<VoiceBehaviors>(voicePath(name, "behavior/status"), {
    signal,
  });
}

export async function setVoiceBehavior(
  http: HttpClient,
  name: string,
  key: string,
  value: unknown,
): Promise<VoiceBehaviors> {
  return http.json<VoiceBehaviors>(
    voicePath(name, "behavior/set"),
    jsonInit("POST", { key, value }),
  );
}

export async function fetchSttUsage(
  http: HttpClient,
  name: string,
): Promise<SttUsage> {
  return http.json<SttUsage>(voicePath(name, "stt/usage"));
}

export async function fetchTtsUsage(
  http: HttpClient,
  name: string,
): Promise<TtsUsage> {
  return http.json<TtsUsage>(voicePath(name, "tts/usage"));
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
