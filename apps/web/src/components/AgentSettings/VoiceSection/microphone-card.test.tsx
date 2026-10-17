import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePreferences } from "@/stores/use-preferences";
import { MicrophoneCard } from "./microphone-card";

const voice = vi.hoisted(() => ({
  allowMicrophone: vi.fn(),
  listMicrophones: vi.fn(),
  microphoneDeniedMessage: vi.fn(),
}));
vi.mock("@/lib/voice", () => voice);

const MICROPHONES = {
  microphones: [
    { id: "usb", label: "USB mic" },
    { id: "built-in", label: "Built-in mic" },
  ],
  named: true,
};

afterEach(() => {
  cleanup();
  usePreferences.getState().update({ voiceInput: null });
  voice.listMicrophones.mockReset();
});

describe("MicrophoneCard", () => {
  it("stores the microphone the user picks, and the default as no device", async () => {
    voice.listMicrophones.mockResolvedValue(MICROPHONES);
    render(<MicrophoneCard />);

    fireEvent.click(await screen.findByText(/input:/));
    fireEvent.click(screen.getByRole("button", { name: "USB mic" }));
    expect(usePreferences.getState().voiceInput).toBe("usb");

    fireEvent.click(screen.getByRole("button", { name: "system default" }));
    expect(usePreferences.getState().voiceInput).toBeNull();
  });

  it("shows the default while the stored microphone is not plugged in", async () => {
    usePreferences.getState().update({ voiceInput: "headset" });
    voice.listMicrophones.mockResolvedValue(MICROPHONES);
    render(<MicrophoneCard />);

    expect(await screen.findByText("system default")).toBeTruthy();
  });

  it("offers to allow the microphone while the browser holds back the names", async () => {
    voice.listMicrophones.mockResolvedValue({
      microphones: [{ id: "a", label: "microphone 1" }],
      named: false,
    });
    render(<MicrophoneCard />);

    expect(await screen.findByRole("button", { name: "allow" })).toBeTruthy();
  });
});
