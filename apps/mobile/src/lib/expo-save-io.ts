import { Directory, File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import type { ApiClient } from "@/api/client";
import { probeAttachmentStatus } from "./attachment-probe";
import type { SaveAttachmentIo } from "./save-attachment";

// The expo edges behind saveAttachment. The download streams to disk natively (an attachment can
// be hundreds of MB), so the gateway path is fetched by uri with the token stamped by authedUrl,
// not through the buffering http client.
export function expoSaveIo(api: ApiClient): SaveAttachmentIo {
  return {
    authedUrl: (path, query) => api.authedUrl(path, query),
    probe: (path) => probeAttachmentStatus(api, path),
    download: async (url, name, onProgress) => {
      const directory = new Directory(Paths.cache, "attachments");
      directory.create({ intermediates: true, idempotent: true });
      // The share sheet shows the file name, so keep the user-visible name (separators aside).
      const destination = new File(directory, name.replaceAll("/", "_"));
      const file = await File.downloadFileAsync(url, destination, {
        idempotent: true,
        ...(onProgress
          ? {
              onProgress: ({ bytesWritten, totalBytes }) => {
                onProgress(bytesWritten, totalBytes);
              },
            }
          : {}),
      });
      return file.uri;
    },
    share: (uri, mimeType) => Sharing.shareAsync(uri, { mimeType }),
  };
}
