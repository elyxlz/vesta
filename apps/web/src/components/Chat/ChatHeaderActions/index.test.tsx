import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("@/api/client", () => ({
  httpClient: { json: vi.fn() },
  authedUrl: vi.fn(() => Promise.resolve("https://host/voice")),
  websocketUrl: vi.fn(() => Promise.resolve("wss://host/voice")),
}));

import { useVoice } from "@/stores/use-voice";
import { ChatHeaderActions } from "./index";

beforeEach(() => {
  useVoice.setState({ speechEnabled: true });
});

afterEach(() => {
  cleanup();
  useVoice.setState({ speechEnabled: false });
});

// Voice is one agent's own service: a peer or group room has nobody to read replies aloud, so the
// mute toggle belongs to a direct room alone.
describe("ChatHeaderActions", () => {
  it("offers the speaker in a direct room", () => {
    const { getByLabelText } = render(<ChatHeaderActions agentName="ada" />);
    expect(getByLabelText("mute voice")).toBeDefined();
  });

  it.each([{ fullscreen: false }, { fullscreen: true }])(
    "hides the speaker in a room with no direct agent (fullscreen $fullscreen)",
    ({ fullscreen }) => {
      const { queryByLabelText } = render(
        <ChatHeaderActions agentName={null} fullscreen={fullscreen} />,
      );
      expect(queryByLabelText("mute voice")).toBeNull();
      expect(queryByLabelText("unmute voice")).toBeNull();
    },
  );
});
