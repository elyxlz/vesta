import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthedMediaUri } from "../visual/harness/authed-media-uri";

const { useAssets } = vi.hoisted(() => ({ useAssets: vi.fn() }));
vi.mock("expo-asset", () => ({ useAssets }));

describe("visual attachment assets", () => {
  beforeEach(() => useAssets.mockReturnValue([undefined, undefined]));

  it("waits for extraction instead of passing Android resource pseudo-paths to native media", () => {
    expect(useAuthedMediaUri(null, "/attachments/att-photo")).toBeNull();
    useAssets.mockReturnValue([
      [
        {
          uri: "file:///android_res/drawable/photo.png",
          localUri: "file:///cache/photo.png",
        },
      ],
      undefined,
    ]);
    expect(
      useAuthedMediaUri(null, "/attachments/att-photo?token=fixture"),
    ).toBe("file:///cache/photo.png");
  });

  it("preserves degraded fixtures and absent media", () => {
    expect(useAuthedMediaUri(null, null)).toBeNull();
    expect(useAuthedMediaUri(null, "/attachments/removed")).toBe(
      "file:///visual-missing-attachment",
    );
  });

  it("uses the resolved asset URI when no local path is needed", () => {
    useAssets.mockReturnValue([
      [{ uri: "file:///bundle/photo.png", localUri: null }],
      undefined,
    ]);
    expect(useAuthedMediaUri(null, "/attachments/att-photo")).toBe(
      "file:///bundle/photo.png",
    );
  });

  it("surfaces asset failures through the real degraded media UI", () => {
    useAssets.mockReturnValue([undefined, new Error("extraction failed")]);
    expect(useAuthedMediaUri(null, "/attachments/att-photo")).toBe(
      "file:///visual-missing-attachment",
    );
  });
});
