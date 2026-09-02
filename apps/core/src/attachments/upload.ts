import { ApiError, type HttpClient } from "../transport/http";
import {
  CHUNK_FAST_MS,
  CHUNK_TIMEOUT_MS,
  INITIAL_CHUNK_BYTES,
  MAX_ATTACHMENT_BYTES,
  MAX_CHUNK_UPLOAD_BYTES,
  MIN_CHUNK_BYTES,
  RETRY_BASE_MS,
  RETRY_MAX_MS,
  type ChatAttachment,
} from "./attachment-model";

// The chunked upload engine: offset-addressed PUTs against the app-chat service, built for spotty
// connections. The server holds the truth about staged bytes (a 409 or a status probe resyncs the
// offset), chunk size adapts to link quality, retryable failures back off forever while the draft
// lives, and an offline link parks the run (no timers burn) until the connectivity edge. Everything
// nondeterministic is injected (timers, clock, connectivity), so the whole machine is unit-testable.

export interface UploadMeta {
  name: string;
  mime: string;
  size: number;
  width?: number;
  height?: number;
  duration_secs?: number;
}

export interface Connectivity {
  isOnline: () => boolean;
  onChange: (callback: (online: boolean) => void) => () => void;
}

export interface UploadDeps {
  connectivity: Connectivity;
  setTimer: (fn: () => void, ms: number) => number;
  clearTimer: (handle: number) => void;
  now: () => number;
}

export type UploadRunState = "uploading" | "waiting";

export interface UploadCallbacks {
  onProgress: (sentBytes: number, totalBytes: number) => void;
  onStateChange: (state: UploadRunState) => void;
}

// Terminal outcomes only; a retryable failure never surfaces here. "aborted" is the caller's own X.
export type UploadErrorReason =
  "too_large" | "unsupported_agent" | "failed" | "aborted";

export class UploadError extends Error {
  readonly reason: UploadErrorReason;

  constructor(reason: UploadErrorReason) {
    super(reason);
    this.reason = reason;
  }
}

export interface UploadHandle {
  result: Promise<ChatAttachment>;
  abort: () => void;
}

interface CreateResponse {
  id: string;
}

interface StatusResponse {
  received: number;
  size: number;
  finalized: boolean;
}

interface CompleteResponse {
  attachment: ChatAttachment;
}

type Verdict = "retryable" | UploadErrorReason;

function classify(error: unknown): Verdict {
  if (error instanceof ApiError) {
    if (error.status === 408 || error.status === 429 || error.status >= 500)
      return "retryable";
    if (error.status === 413) return "too_large";
    return "failed";
  }
  // Network failures, aborted fetches, malformed responses: all worth another try.
  return "retryable";
}

export interface UploadRequest {
  agent: string;
  blob: Blob;
  meta: UploadMeta;
}

export function uploadAttachment(
  http: HttpClient,
  request: UploadRequest,
  deps: UploadDeps,
  callbacks: UploadCallbacks,
): UploadHandle {
  const { agent, blob, meta } = request;
  const base = `/agents/${encodeURIComponent(agent)}/app-chat/attachments`;
  // Aborts every non-chunk request in flight (create, status probe, complete) the moment the caller
  // gives up; chunk PUTs carry their own controller so the stall timeout can abort just one chunk.
  const runAbort = new AbortController();
  let aborted = false;
  let abortInFlight: (() => void) | null = null;
  let wake: (() => void) | null = null;

  const checkAborted = () => {
    if (aborted) throw new UploadError("aborted");
  };

  // A cancellable sleep: abort() (or an online edge, via wake) releases it early.
  const sleep = (ms: number) =>
    new Promise<void>((resolve) => {
      const handle = deps.setTimer(() => {
        wake = null;
        resolve();
      }, ms);
      wake = () => {
        deps.clearTimer(handle);
        wake = null;
        resolve();
      };
    });

  const onlineEdge = () =>
    new Promise<void>((resolve) => {
      const unsubscribe = deps.connectivity.onChange((online) => {
        if (!online) return;
        unsubscribe();
        wake = null;
        resolve();
      });
      wake = () => {
        unsubscribe();
        wake = null;
        resolve();
      };
    });

  const jsonPost = <T>(path: string, body: unknown) =>
    http.json<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: runAbort.signal,
    });

  const backoffMs = (attempt: number) =>
    Math.min(RETRY_BASE_MS * 2 ** attempt, RETRY_MAX_MS);

  // Park until the link plausibly works again: an offline link waits for the connectivity edge
  // (no timer burns), an online-but-failing one backs off. Emits the waiting/uploading pair.
  const park = async (attempt: number) => {
    callbacks.onStateChange("waiting");
    if (deps.connectivity.isOnline()) await sleep(backoffMs(attempt));
    else await onlineEdge();
    checkAborted();
    callbacks.onStateChange("uploading");
  };

  // Where to continue: the server's staged size. Throws when the probe itself fails, so callers
  // decide between keeping their guess (post-park resync) and parking (the 409 path, where an
  // immediate retry would busy-loop against a broken link).
  const probeOffset = async (id: string): Promise<number> => {
    const status = await http.json<StatusResponse>(`${base}/${id}/status`, {
      signal: runAbort.signal,
    });
    return status.finalized ? meta.size : status.received;
  };

  const putChunk = async (id: string, offset: number, chunk: Blob) => {
    const inFlight = new AbortController();
    const timeout = deps.setTimer(() => {
      inFlight.abort();
    }, CHUNK_TIMEOUT_MS);
    abortInFlight = () => {
      inFlight.abort();
    };
    try {
      await http.json(`${base}/${id}/data?offset=${String(offset)}`, {
        method: "PUT",
        body: chunk,
        signal: inFlight.signal,
      });
    } finally {
      abortInFlight = null;
      deps.clearTimer(timeout);
    }
  };

  const createSession = async (): Promise<string> => {
    for (let attempt = 0; ; attempt += 1) {
      checkAborted();
      try {
        const created = await jsonPost<CreateResponse>(base, meta);
        return created.id;
      } catch (error) {
        checkAborted();
        if (error instanceof ApiError && error.status === 404)
          throw new UploadError("unsupported_agent");
        const verdict = classify(error);
        if (verdict !== "retryable") throw new UploadError(verdict);
        await park(attempt);
      }
    }
  };

  const sendChunks = async (id: string) => {
    let offset = 0;
    let chunkBytes = Math.min(INITIAL_CHUNK_BYTES, MAX_CHUNK_UPLOAD_BYTES);
    let attempt = 0;
    callbacks.onProgress(0, meta.size);
    while (offset < meta.size) {
      checkAborted();
      const chunk = blob.slice(
        offset,
        Math.min(offset + chunkBytes, meta.size),
      );
      const started = deps.now();
      try {
        await putChunk(id, offset, chunk);
        offset += chunk.size;
        attempt = 0;
        callbacks.onProgress(offset, meta.size);
        if (deps.now() - started < CHUNK_FAST_MS)
          chunkBytes = Math.min(chunkBytes * 2, MAX_CHUNK_UPLOAD_BYTES);
        continue;
      } catch (error) {
        checkAborted();
        if (error instanceof ApiError && error.status === 409) {
          const staged = await probeStagedOffset(id);
          if (staged !== null) {
            offset = staged;
            continue;
          }
        } else {
          const verdict = classify(error);
          if (verdict !== "retryable") throw new UploadError(verdict);
          chunkBytes = Math.max(Math.floor(chunkBytes / 2), MIN_CHUNK_BYTES);
        }
        await park(attempt);
        attempt += 1;
        offset = await recoveredOffset(id, offset);
      }
    }
  };

  // Offset drift, including the lost-response replay: adopt the server's staged size. A failed
  // probe answers null so the caller parks like any retryable failure, never a zero-delay re-PUT.
  const probeStagedOffset = async (id: string): Promise<number | null> => {
    try {
      const staged = await probeOffset(id);
      callbacks.onProgress(Math.min(staged, meta.size), meta.size);
      return staged;
    } catch (probeError) {
      checkAborted();
      const verdict = classify(probeError);
      if (verdict !== "retryable") throw new UploadError(verdict);
      return null;
    }
  };

  // After a park: resync with the server, or keep the current guess so the next PUT's 409 re-enters
  // recovery.
  const recoveredOffset = async (
    id: string,
    fallback: number,
  ): Promise<number> => {
    try {
      const staged = await probeOffset(id);
      callbacks.onProgress(Math.min(staged, meta.size), meta.size);
      return staged;
    } catch {
      return fallback;
    }
  };

  const complete = async (id: string): Promise<ChatAttachment> => {
    for (let attempt = 0; ; attempt += 1) {
      checkAborted();
      try {
        const done = await jsonPost<CompleteResponse>(
          `${base}/${id}/complete`,
          {},
        );
        return done.attachment;
      } catch (error) {
        checkAborted();
        // A complete 409 is a size mismatch: the staged bytes are wrong, no retry can fix them.
        if (error instanceof ApiError && error.status === 409)
          throw new UploadError("failed");
        const verdict = classify(error);
        if (verdict !== "retryable") throw new UploadError(verdict);
        await park(attempt);
      }
    }
  };

  const run = async (): Promise<ChatAttachment> => {
    if (meta.size > MAX_ATTACHMENT_BYTES) throw new UploadError("too_large");
    callbacks.onStateChange("uploading");
    const id = await createSession();
    await sendChunks(id);
    return complete(id);
  };

  const result = run();
  // The caller may abort and walk away; the rejection is still delivered to `result` awaiters.
  result.catch(() => undefined);
  return {
    result,
    abort: () => {
      if (aborted) return;
      aborted = true;
      runAbort.abort();
      abortInFlight?.();
      wake?.();
    },
  };
}
