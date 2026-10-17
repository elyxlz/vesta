import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  authedUrl: vi.fn(),
  httpClient: {},
  websocketUrl: vi.fn(),
}));

const { browserCapture, listMicrophones, microphoneDeniedMessage } =
  await import("./voice");

function device(kind: MediaDeviceKind, deviceId: string, label: string) {
  return { kind, deviceId, label, groupId: "", toJSON: () => ({}) };
}

function stubMediaDevices(media: Partial<MediaDevices>) {
  vi.stubGlobal("navigator", { mediaDevices: media });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listMicrophones", () => {
  it("lists each input once, without the browser's default aliases", async () => {
    stubMediaDevices({
      enumerateDevices: () =>
        Promise.resolve([
          device("audioinput", "default", "Default - USB mic"),
          device("audioinput", "communications", "Communications - USB mic"),
          device("audioinput", "usb", "USB mic"),
          device("audioinput", "built-in", "Built-in mic"),
          device("audiooutput", "speakers", "Speakers"),
        ]),
    });

    expect(await listMicrophones()).toEqual({
      microphones: [
        { id: "usb", label: "USB mic" },
        { id: "built-in", label: "Built-in mic" },
      ],
      named: true,
    });
  });

  it("numbers the inputs while the browser holds back their names", async () => {
    stubMediaDevices({
      enumerateDevices: () =>
        Promise.resolve([
          device("audioinput", "a", ""),
          device("audioinput", "b", ""),
        ]),
    });

    expect(await listMicrophones()).toEqual({
      microphones: [
        { id: "a", label: "microphone 1" },
        { id: "b", label: "microphone 2" },
      ],
      named: false,
    });
  });
});

describe("browserCapture", () => {
  it.each([
    { input: "usb", expected: "usb" },
    { input: null, expected: undefined },
  ])("asks for the chosen microphone ($input)", async ({ input, expected }) => {
    const getUserMedia = vi.fn<MediaDevices["getUserMedia"]>(() =>
      Promise.reject(new DOMException("none", "NotFoundError")),
    );
    stubMediaDevices({ getUserMedia });

    await expect(
      browserCapture(
        () => false,
        () => input,
      ).start(() => undefined),
    ).rejects.toThrow("No microphone found");

    const audio = getUserMedia.mock.calls[0]?.[0]?.audio;
    expect(typeof audio === "object" ? audio.deviceId : null).toBe(expected);
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
