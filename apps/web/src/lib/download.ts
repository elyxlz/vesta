import { appChatAttachmentPath, type ChatAttachment } from "@vesta/core";
import { ApiError, apiFetch } from "@/api/client";

declare global {
  interface Window {
    showSaveFilePicker?: (options?: {
      suggestedName?: string;
    }) => Promise<FileSystemFileHandle>;
  }
}

// The one owner of "this blob was freed by the agent's cleanup": the serve route answers 410 for a
// removed attachment, the terminal state every surface renders as "no longer available".
export function attachmentRemoved(error: unknown): boolean {
  return error instanceof ApiError && error.status === 410;
}

export type DownloadOutcome = "saved" | "cancelled";

// Download an attachment through the header-authed client (no token in any visible URL): fetch to a
// Blob with progress, then save it. Chromium (including the desktop app) uses the File System Access
// picker, which resolves only once the file is actually written and rejects when the user cancels, so
// "saved" is truthful; Firefox and Safari fall back to an object-URL anchor click, which the browser
// owns and never reports on, so there it is optimistic. The proxy strips Content-Length from streamed
// responses, so progress reads received bytes against the metadata size the caller already holds.
export async function downloadAttachment(
  agent: string,
  attachment: ChatAttachment,
  onProgress?: (receivedBytes: number, totalBytes: number) => void,
): Promise<DownloadOutcome> {
  const response = await apiFetch(
    appChatAttachmentPath(agent, attachment.id, true),
  );
  const blob = await readWithProgress(response, attachment.size, onProgress);
  return saveBlob(blob, attachment.name);
}

async function saveBlob(blob: Blob, name: string): Promise<DownloadOutcome> {
  if (typeof window.showSaveFilePicker === "function") {
    let handle: FileSystemFileHandle;
    try {
      handle = await window.showSaveFilePicker({ suggestedName: name });
    } catch (error) {
      // Dismissing the picker is a cancel, not a failure.
      if (error instanceof DOMException && error.name === "AbortError")
        return "cancelled";
      throw error;
    }
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return "saved";
  }
  // Firefox/Safari: an object-URL anchor click the browser owns and never reports on.
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return "saved";
}

async function readWithProgress(
  response: Response,
  totalBytes: number,
  onProgress?: (receivedBytes: number, totalBytes: number) => void,
): Promise<Blob> {
  const body = response.body;
  if (!body || !onProgress) return response.blob();
  const reader = body.getReader();
  const parts: BlobPart[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    received += value.byteLength;
    onProgress(received, totalBytes);
  }
  return new Blob(parts);
}
