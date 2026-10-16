import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SettingDef } from "@/lib/voice";
import { DynamicSettings } from "./setting-controls";

const voice = vi.hoisted(() => ({
  setVoiceBehavior: vi.fn(),
  setVoiceSetting: vi.fn(),
}));
vi.mock("@/lib/voice", () => voice);

function bool(key: string, value: boolean): SettingDef {
  return { key, type: "bool", label: key, value };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  voice.setVoiceBehavior.mockReset();
  voice.setVoiceSetting.mockReset();
});

describe("DynamicSettings", () => {
  it("saves a behavior through the behavior route and takes its answer", async () => {
    voice.setVoiceBehavior.mockResolvedValue({
      settings: [bool("barge_in", false)],
    });
    const onSettingChange = vi.fn();
    render(
      <DynamicSettings
        settings={[bool("barge_in", true)]}
        section="behavior"
        agentName="ada"
        onSettingChange={onSettingChange}
      />,
    );

    fireEvent.click(screen.getByRole("switch"));

    await vi.waitFor(() => {
      expect(onSettingChange).toHaveBeenCalledWith([bool("barge_in", false)]);
    });
    expect(voice.setVoiceBehavior).toHaveBeenCalledWith(
      "ada",
      "barge_in",
      false,
    );
    expect(voice.setVoiceSetting).not.toHaveBeenCalled();
  });

  it("shows the stored value again when a save fails", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    voice.setVoiceSetting.mockRejectedValue(new Error("offline"));
    render(
      <DynamicSettings
        settings={[bool("smart_format", true)]}
        section="stt"
        agentName="ada"
        onSettingChange={vi.fn()}
      />,
    );
    const toggle = screen.getByRole("switch");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");

    await vi.waitFor(() => {
      expect(toggle.getAttribute("aria-checked")).toBe("true");
    });
    expect(voice.setVoiceSetting).toHaveBeenCalledWith(
      "ada",
      "stt",
      "smart_format",
      false,
    );
  });
});
