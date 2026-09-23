import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  authedUrl: vi.fn(),
  httpClient: {},
  websocketUrl: vi.fn(),
}));

const { browserCapture, microphoneDeniedMessage } = await import("./voice");

interface FakeTrack {
  stop: ReturnType<typeof vi.fn>;
}

function pendingMicrophone() {
  const track: FakeTrack = { stop: vi.fn() };
  let grant: () => void = () => undefined;
  const getUserMedia = vi.fn(
    () =>
      new Promise((resolve) => {
        grant = () => {
          resolve({ getTracks: () => [track] });
        };
      }),
  );
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  const audioContext = vi.fn();
  vi.stubGlobal("AudioContext", audioContext);
  return { track, audioContext, grant: () => grant() };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("browserCapture", () => {
  it("releases a microphone granted after the capture was stopped", async () => {
    const mic = pendingMicrophone();
    const capture = browserCapture();

    const started = capture.start(() => undefined);
    capture.stop();
    mic.grant();
    await started;

    expect(mic.track.stop).toHaveBeenCalledOnce();
    expect(mic.audioContext).not.toHaveBeenCalled();
  });
});

describe("microphoneDeniedMessage", () => {
  it.each([
    { isDesktopApp: true, platform: "macos", expected: "System Settings" },
    { isDesktopApp: true, platform: "windows", expected: "Settings > Privacy" },
    { isDesktopApp: false, platform: "macos", expected: "browser settings" },
    { isDesktopApp: false, platform: "windows", expected: "browser settings" },
  ] as const)(
    "names where to turn it on ($platform, desktop app: $isDesktopApp)",
    ({ isDesktopApp, platform, expected }) => {
      expect(microphoneDeniedMessage({ isDesktopApp, platform })).toContain(
        expected,
      );
    },
  );
});
