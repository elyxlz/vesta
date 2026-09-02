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
  return http.json<VoiceStatus>(voicePath(name, `${domain}/status`), {
    signal,
  });
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
  return http.json<VoiceStatus>(
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
  return http.json<VoiceStatus>(
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
