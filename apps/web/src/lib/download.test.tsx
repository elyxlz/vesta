import { afterEach, describe, expect, it, vi } from "vitest";

import { httpClient } from "@/api/client";
import { downloadAttachment } from "./download";

vi.mock("@/api/client", () => ({ httpClient: { request: vi.fn() } }));

const apiFetchMock = vi.mocked(httpClient.request);

const ATTACHMENT = {
  id: "att1",
  name: "report.pdf",
  mime: "application/pdf",
  size: 8,
};

describe("downloadAttachment", () => {
  afterEach(() => {
    window.showSaveFilePicker = undefined;
    vi.restoreAllMocks();
  });

  it("fetches the download form and clicks a same-origin blob anchor", async () => {
    apiFetchMock.mockResolvedValue(new Response(new Uint8Array(8)));
    const createUrl = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:fake");
    const revokeUrl = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    await downloadAttachment("ada", ATTACHMENT);

    expect(apiFetchMock).toHaveBeenCalledWith(
      "/agents/ada/chat/attachments/att1?download=1",
    );
    expect(createUrl).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeUrl).toHaveBeenCalledWith("blob:fake");
  });

  it("reports progress against the metadata size while streaming", async () => {
    const chunks = [new Uint8Array(3), new Uint8Array(5)];
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
      },
    });
    apiFetchMock.mockResolvedValue(new Response(stream));
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );
    const progress: [number, number][] = [];

    await downloadAttachment("ada", ATTACHMENT, (received, total) => {
      progress.push([received, total]);
    });

    expect(progress).toEqual([
      [3, 8],
      [8, 8],
    ]);
  });

  it("propagates a failed fetch to the caller", async () => {
    apiFetchMock.mockRejectedValue(new Error("410"));
    await expect(downloadAttachment("ada", ATTACHMENT)).rejects.toThrow("410");
  });

  it("writes through the file picker and reports saved", async () => {
    apiFetchMock.mockResolvedValue(new Response(new Uint8Array(8)));
    const write = vi.fn(() => Promise.resolve());
    const close = vi.fn(() => Promise.resolve());
    const writable = {
      write,
      close,
    } as unknown as FileSystemWritableFileStream;
    const handle = {
      createWritable: () => Promise.resolve(writable),
    } as unknown as FileSystemFileHandle;
    const picker = vi.fn(() => Promise.resolve(handle));
    window.showSaveFilePicker = picker;

    const outcome = await downloadAttachment("ada", ATTACHMENT);

    expect(picker).toHaveBeenCalledWith({ suggestedName: "report.pdf" });
    expect(write).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
    expect(outcome).toBe("saved");
  });

  it("returns cancelled when the save picker is dismissed", async () => {
    apiFetchMock.mockResolvedValue(new Response(new Uint8Array(8)));
    window.showSaveFilePicker = vi.fn(() =>
      Promise.reject(new DOMException("cancelled", "AbortError")),
    );

    await expect(downloadAttachment("ada", ATTACHMENT)).resolves.toBe(
      "cancelled",
    );
  });
});
