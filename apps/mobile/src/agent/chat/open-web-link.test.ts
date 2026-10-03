import { beforeEach, describe, expect, it, vi } from "vitest";

const openInOwningAppAsync = vi.fn<(url: string) => Promise<boolean>>();
const openBrowserAsync = vi.fn<(url: string) => Promise<void>>();

vi.mock("expo", () => ({
  requireOptionalNativeModule: vi.fn(() => ({ openInOwningAppAsync })),
}));
vi.mock("expo-web-browser", () => ({ openBrowserAsync }));

const { openWebLink } = await import("./open-web-link");

const MAPS_URL = "https://maps.app.goo.gl/abc";

describe("openWebLink", () => {
  beforeEach(() => {
    openInOwningAppAsync.mockReset();
    openBrowserAsync.mockReset();
  });

  it("hands the link to the app that owns it", async () => {
    openInOwningAppAsync.mockResolvedValue(true);

    await openWebLink(MAPS_URL);

    expect(openInOwningAppAsync).toHaveBeenCalledWith(MAPS_URL);
    expect(openBrowserAsync).not.toHaveBeenCalled();
  });

  it("opens the in-app browser when no app owns the link", async () => {
    openInOwningAppAsync.mockResolvedValue(false);

    await openWebLink(MAPS_URL);

    expect(openBrowserAsync).toHaveBeenCalledWith(MAPS_URL);
  });
});
