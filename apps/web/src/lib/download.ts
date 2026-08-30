import { appChatAttachmentPath, type ChatAttachment } from "@vesta/core";
import { apiFetch } from "@/api/client";

// Download an attachment through the header-authed client (no token in any visible URL): fetch to
// a Blob, then a same-origin object-URL anchor click, which works identically in the browser and
// Electron (where the desktop's will-download handler routes it to the OS save dialog). The proxy
// strips Content-Length from streamed responses, so progress reads the received bytes against the
// metadata size the caller already holds.
export async function downloadAttachment(
  agent: string,
  attachment: ChatAttachment,
  onProgress?: (receivedBytes: number, totalBytes: number) => void,
): Promise<void> {
  const response = await apiFetch(
    appChatAttachmentPath(agent, attachment.id, true),
  );
  const blob = await readWithProgress(response, attachment.size, onProgress);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = attachment.name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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
