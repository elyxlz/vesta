import { beforeEach, describe, expect, it, vi } from "vitest";

const os = vi.hoisted(() => ({
  cameraGranted: true,
  cameraCanAskAgain: true,
  requestGrants: true,
  requestCalls: 0,
  libraryResult: { canceled: true } as unknown,
  cameraResult: { canceled: true } as unknown,
  documentResult: { canceled: true } as unknown,
}));

vi.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: () =>
    Promise.resolve({
      granted: os.cameraGranted,
      canAskAgain: os.cameraCanAskAgain,
    }),
  requestCameraPermissionsAsync: () => {
    os.requestCalls += 1;
    return Promise.resolve({
      granted: os.requestGrants,
      canAskAgain: os.cameraCanAskAgain,
    });
  },
  launchImageLibraryAsync: () => Promise.resolve(os.libraryResult),
  launchCameraAsync: () => Promise.resolve(os.cameraResult),
}));
vi.mock("expo-document-picker", () => ({
  getDocumentAsync: () => Promise.resolve(os.documentResult),
}));
vi.mock("react-native", () => ({ Linking: { openSettings: vi.fn() } }));

import {
  assetToBlob,
  captureFromCamera,
  pickDocuments,
  pickFromLibrary,
} from "./pick";

beforeEach(() => {
  os.cameraGranted = true;
  os.cameraCanAskAgain = true;
  os.requestGrants = true;
  os.requestCalls = 0;
  os.libraryResult = { canceled: true };
  os.cameraResult = { canceled: true };
  os.documentResult = { canceled: true };
});

describe("pickFromLibrary", () => {
  it("normalizes picker assets, converting duration to seconds", async () => {
    os.libraryResult = {
      canceled: false,
      assets: [
        {
          uri: "file:///tmp/IMG_1.jpg",
          fileName: "IMG_1.jpg",
          mimeType: "image/jpeg",
          width: 4032,
          height: 3024,
        },
        {
          uri: "content://media/clip",
          fileName: null,
          mimeType: "video/mp4",
          width: 1920,
          height: 1080,
          duration: 12500,
        },
      ],
    };

    const result = await pickFromLibrary();

    expect(result).toEqual({
      status: "picked",
      assets: [
        {
          uri: "file:///tmp/IMG_1.jpg",
          name: "IMG_1.jpg",
          mime: "image/jpeg",
          width: 4032,
          height: 3024,
        },
        {
          uri: "content://media/clip",
          name: "clip",
          mime: "video/mp4",
          width: 1920,
          height: 1080,
          durationSecs: 12.5,
        },
      ],
    });
  });

  it("reports a cancel", async () => {
    expect(await pickFromLibrary()).toEqual({ status: "cancelled" });
  });
});

describe("captureFromCamera", () => {
  it("prompts once when undecided and captures on grant", async () => {
    os.cameraGranted = false;
    os.cameraResult = {
      canceled: false,
      assets: [{ uri: "file:///tmp/cap.jpg", fileName: "cap.jpg", mimeType: "image/jpeg" }],
    };

    const result = await captureFromCamera();

    expect(os.requestCalls).toBe(1);
    if (result.status !== "picked") throw new Error("expected a capture");
    expect(result.assets[0]?.name).toBe("cap.jpg");
  });

  it("reports blocked when the OS will not ask again", async () => {
    os.cameraGranted = false;
    os.cameraCanAskAgain = false;
    expect(await captureFromCamera()).toEqual({ status: "blocked" });
    expect(os.requestCalls).toBe(0);
  });

  it("reports a plain denial as cancelled", async () => {
    os.cameraGranted = false;
    os.requestGrants = false;
    expect(await captureFromCamera()).toEqual({ status: "cancelled" });
  });
});

describe("pickDocuments", () => {
  it("normalizes document assets", async () => {
    os.documentResult = {
      canceled: false,
      assets: [{ uri: "file:///tmp/report.pdf", name: "report.pdf", mimeType: "application/pdf", size: 9 }],
    };
    expect(await pickDocuments()).toEqual({
      status: "picked",
      assets: [{ uri: "file:///tmp/report.pdf", name: "report.pdf", mime: "application/pdf" }],
    });
  });
});

describe("assetToBlob", () => {
  it("fetches the asset uri into a sliceable blob", async () => {
    const blob = new Blob([new Uint8Array(6)]);
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(blob));

    const result = await assetToBlob({ uri: "file:///tmp/a.bin", name: "a.bin", mime: "application/octet-stream" });

    expect(fetchSpy).toHaveBeenCalledWith("file:///tmp/a.bin");
    expect(result.size).toBe(6);
    fetchSpy.mockRestore();
  });
});
