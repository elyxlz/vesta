import { describe, expect, it, vi } from "vitest";
import type { ChatAttachment } from "@vesta/core";
import {
  AttachmentRemovedError,
  saveAttachment,
  type SaveAttachmentIo,
} from "./save-attachment";

const ATTACHMENT: ChatAttachment = {
  id: "att1",
  name: "report.pdf",
  mime: "application/pdf",
  size: 4096,
};

function io(overrides: Partial<SaveAttachmentIo> = {}): SaveAttachmentIo {
  return {
    authedUrl: (path) => Promise.resolve(`https://gw.example${path}&token=t`),
    probe: () => Promise.resolve(200),
    download: () => Promise.resolve("file:///cache/report.pdf"),
    share: () => Promise.resolve(),
    ...overrides,
  };
}

describe("saveAttachment", () => {
  it("downloads the token-stamped download url then opens the share sheet", async () => {
    const download = vi.fn((url: string): Promise<string> =>
      Promise.resolve(`file:///cache/${url.length.toString()}`),
    );
    const share = vi.fn((): Promise<void> => Promise.resolve());
    await saveAttachment(
      io({
        download: (url, name, onProgress) => {
          void name;
          void onProgress;
          return download(url);
        },
        share: (uri, mimeType) => {
          void uri;
          void mimeType;
          return share();
        },
      }),
      "apollo",
      ATTACHMENT,
    );
    const url = download.mock.calls[0]?.[0] ?? "";
    expect(url).toContain("/agents/apollo/app-chat/attachments/att1");
    expect(url).toContain("download=1");
    expect(url).toContain("token=t");
    expect(share).toHaveBeenCalledTimes(1);
  });

  it("surfaces a removed blob as AttachmentRemovedError via the probe", async () => {
    const attempt = saveAttachment(
      io({
        download: () => Promise.reject(new Error("UnableToDownload: 410")),
        probe: () => Promise.resolve(410),
      }),
      "apollo",
      ATTACHMENT,
    );
    await expect(attempt).rejects.toBeInstanceOf(AttachmentRemovedError);
  });

  it("rethrows the original failure when the probe says the blob still exists", async () => {
    const failure = new Error("network down");
    const attempt = saveAttachment(
      io({
        download: () => Promise.reject(failure),
        probe: () => Promise.reject(new Error("also down")),
      }),
      "apollo",
      ATTACHMENT,
    );
    await expect(attempt).rejects.toBe(failure);
  });

  it("never opens the share sheet when the download failed", async () => {
    const share = vi.fn((): Promise<void> => Promise.resolve());
    await saveAttachment(
      io({
        download: () => Promise.reject(new Error("boom")),
        share: () => share(),
      }),
      "apollo",
      ATTACHMENT,
    ).catch(() => undefined);
    expect(share).not.toHaveBeenCalled();
  });
});
