import { describe, expect, it, vi } from "vitest";
import type { HttpClient } from "../transport/http";
import {
  bargeInEnabled,
  fetchVoiceStatus,
  type SettingDef,
  type VoiceBehaviors,
} from "./voice";

function setting(key: string, value: unknown): SettingDef {
  return { key, type: "bool", label: "", value };
}

function behaviors(value: unknown): VoiceBehaviors {
  return { settings: [setting("barge_in", value)] };
}

describe("bargeInEnabled", () => {
  it("is off only when the behavior says off", () => {
    expect(bargeInEnabled(behaviors(false))).toBe(false);
    expect(bargeInEnabled(behaviors(true))).toBe(true);
  });

  it("is on for an agent that reports no behaviors", () => {
    expect(bargeInEnabled(null)).toBe(true);
    expect(bargeInEnabled({ settings: [] })).toBe(true);
  });
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
