import { describe, expect, it, vi } from "vitest";
import { ApiError, type HttpClient } from "../transport/http";
import {
  fetchVoiceSettings,
  fetchVoiceStatus,
  setVoiceBehavior,
  ttsStreamQuery,
  type SettingDef,
  type VoiceStatus,
} from "./voice";

function setting(key: string, value: unknown): SettingDef {
  return { key, type: "bool", label: "", value };
}

describe("ttsStreamQuery", () => {
  it.each([
    { playsOggOpus: true, expected: "opus_48000,mp3_44100,mp3_22050" },
    { playsOggOpus: false, expected: "mp3_44100,mp3_22050" },
  ])(
    "names the formats the player decodes (opus: $playsOggOpus)",
    ({ playsOggOpus, expected }) => {
      expect(ttsStreamQuery(playsOggOpus).get("formats")).toBe(expected);
    },
  );
});

describe("fetchVoiceStatus", () => {
  it("drops the interrupt_tts setting that an older voice service still lists", async () => {
    const http: HttpClient = {
      request: vi.fn(),
      json: vi.fn().mockResolvedValue({
        configured: true,
        provider: "deepgram",
        enabled: true,
        settings: [
          setting("interrupt_tts", false),
          setting("multi_language", true),
        ],
      }),
    };

    const status = await fetchVoiceStatus(http, "luna", "stt");

    expect(status.settings).toEqual([setting("multi_language", true)]);
  });
});

const ROLE: VoiceStatus = { configured: true, provider: "deepgram" };

// A voice service that answers the STT and TTS status and fails the judge and behavior routes.
function withoutJudge(error: Error): HttpClient {
  return {
    request: vi.fn(),
    json: vi
      .fn()
      .mockImplementation((path: string) =>
        /judge|behavior/.test(path)
          ? Promise.reject(error)
          : Promise.resolve(ROLE),
      ),
  };
}

describe("fetchVoiceSettings", () => {
  it("reads the judge and the behaviors as none when the voice service has no route for them", async () => {
    const http = withoutJudge(new ApiError(404, "not found"));

    await expect(fetchVoiceSettings(http, "luna", "web")).resolves.toEqual({
      stt: ROLE,
      tts: ROLE,
      judge: null,
      behaviors: null,
    });
  });

  it("passes every other failure on", async () => {
    const http = withoutJudge(new ApiError(502, "bad gateway"));

    await expect(fetchVoiceSettings(http, "luna", "web")).rejects.toThrow(
      "bad gateway",
    );
  });

  it("asks for the behaviors of its own client kind", async () => {
    const json = vi.fn().mockResolvedValue(ROLE);

    await fetchVoiceSettings({ request: vi.fn(), json }, "luna", "desktop");

    expect(json).toHaveBeenCalledWith(
      "/agents/luna/voice/behavior/status?client=desktop",
      expect.anything(),
    );
  });
});

describe("setVoiceBehavior", () => {
  it("sets the value of its own client kind", async () => {
    const json = vi.fn().mockResolvedValue({ settings: [] });

    await setVoiceBehavior(
      { request: vi.fn(), json },
      "luna",
      "mobile",
      "barge_in",
      false,
    );

    expect(json).toHaveBeenCalledWith(
      "/agents/luna/voice/behavior/set",
      expect.objectContaining({
        body: JSON.stringify({
          key: "barge_in",
          value: false,
          client: "mobile",
        }),
      }),
    );
  });
});
