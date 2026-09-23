import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  authedUrl: vi.fn(),
  httpClient: {},
  websocketUrl: vi.fn(),
}));

const { browserCapture } = await import("./voice");

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
