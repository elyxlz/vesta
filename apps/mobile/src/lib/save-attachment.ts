import { appChatAttachmentPath, type ChatAttachment } from "@vesta/core";

// Saving an attachment on mobile is a native download to the app cache followed by the system
// share sheet, which is where "save to Files/Photos" lives on both platforms. The expo edges
// live in expo-save-io.ts; this module owns only the flow, so the suite runs in plain node.

export class AttachmentRemovedError extends Error {
  constructor() {
    super("This attachment was removed on the agent");
    this.name = "AttachmentRemovedError";
  }
}

export interface SaveAttachmentIo {
  authedUrl: (path: string, query: URLSearchParams) => Promise<string>;
  probe: (path: string) => Promise<number>;
  download: (
    url: string,
    name: string,
    onProgress?: (written: number, total: number) => void,
  ) => Promise<string>;
  share: (uri: string, mimeType: string) => Promise<void>;
}

export async function saveAttachment(
  io: SaveAttachmentIo,
  agent: string,
  attachment: ChatAttachment,
  onProgress?: (written: number, total: number) => void,
): Promise<void> {
  // The query rides authedUrl's params (the token joins them there); a `?` baked into the path
  // would produce a second `?` and an unauthenticated URL.
  const path = appChatAttachmentPath(agent, attachment.id);
  const url = await io.authedUrl(path, new URLSearchParams({ download: "1" }));
  let uri: string;
  try {
    uri = await io.download(url, attachment.name, onProgress);
  } catch (error) {
    // The native download API hides the HTTP status, so a failure is classified by re-asking
    // the server: a removed blob is a stable 410, anything else rethrows as the transient it is.
    const status = await io.probe(path).catch(() => 0);
    if (status === 410) throw new AttachmentRemovedError();
    throw error;
  }
  await io.share(uri, attachment.mime);
}
