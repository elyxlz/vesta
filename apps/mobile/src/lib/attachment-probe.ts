import { ApiError, type ApiClient } from "@/api/client";

// A bodyless HEAD whose answer is the status alone. The transport throws ApiError on every
// non-2xx, so the interesting statuses (410 removed) come out of the error, never a Response.
export async function probeAttachmentStatus(
  api: ApiClient,
  path: string,
): Promise<number> {
  try {
    return (await api.request(path, { method: "HEAD" })).status;
  } catch (error) {
    if (error instanceof ApiError) return error.status;
    throw error;
  }
}
