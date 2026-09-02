import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type HttpClient } from "../transport/http";
import {
  CHUNK_FAST_MS,
  INITIAL_CHUNK_BYTES,
  MAX_ATTACHMENT_BYTES,
  MAX_CHUNK_UPLOAD_BYTES,
  MIN_CHUNK_BYTES,
  RETRY_BASE_MS,
  type ChatAttachment,
} from "./attachment-model";
import {
  UploadError,
  uploadAttachment,
  type Connectivity,
  type UploadRunState,
} from "./upload";

interface Call {
  path: string;
  init: RequestInit | undefined;
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
}

function scriptedHttp() {
  const queued: Call[] = [];
  const waiters: ((call: Call) => void)[] = [];
  const http: HttpClient = {
    request: () => {
      throw new Error("request() is unused by the upload engine");
    },
    json: <T>(path: string, init?: RequestInit) =>
      new Promise<T>((resolve, reject) => {
        const call: Call = {
          path,
          init,
          resolve: resolve as (value: unknown) => void,
          reject,
        };
        // Model real fetch: an aborted signal rejects the in-flight request.
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
        const waiter = waiters.shift();
        if (waiter) waiter(call);
        else queued.push(call);
      }),
  };
  const next = (): Promise<Call> =>
    new Promise((resolve) => {
      const call = queued.shift();
      if (call) resolve(call);
      else waiters.push(resolve);
    });
  return { http, next };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function harness(online = true) {
  let time = 0;
  let isOnline = online;
  const listeners = new Set<(online: boolean) => void>();
  const connectivity: Connectivity = {
    isOnline: () => isOnline,
    onChange: (callback) => {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
  };
  const progress: [number, number][] = [];
  const states: UploadRunState[] = [];
  return {
    deps: {
      connectivity,
      now: () => time,
    },
    callbacks: {
      onProgress: (sent: number, total: number) => {
        progress.push([sent, total]);
      },
      onStateChange: (state: UploadRunState) => {
        states.push(state);
      },
    },
    progress,
    states,
    advance: (ms: number) => {
      time += ms;
    },
    setOnline: (value: boolean) => {
      isOnline = value;
      for (const callback of [...listeners]) callback(value);
    },
  };
}

const META = { name: "video.bin", mime: "application/octet-stream", size: 0 };

function start(http: HttpClient, size: number, run = harness()) {
  const blob = new Blob([new Uint8Array(size)]);
  const handle = uploadAttachment(
    http,
    { agent: "apollo", blob, meta: { ...META, size } },
    run.deps,
    run.callbacks,
  );
  return { handle, run };
}

const DONE: ChatAttachment = {
  id: "att1",
  name: "video.bin",
  mime: "application/octet-stream",
  size: 3,
};

// Let the engine's awaited catch/park path run to its next suspension point.
const settle = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(0);
};

describe("uploadAttachment", () => {
  it("creates, PUTs sequential offsets, completes, and reports progress", async () => {
    const { http, next } = scriptedHttp();
    const size = INITIAL_CHUNK_BYTES + 10;
    const { handle, run } = start(http, size);

    const create = await next();
    expect(create.path).toBe("/agents/apollo/app-chat/attachments");
    create.resolve({ id: "att1" });

    const first = await next();
    expect(first.path).toBe(
      "/agents/apollo/app-chat/attachments/att1/data?offset=0",
    );
    expect((first.init?.body as Blob).size).toBe(INITIAL_CHUNK_BYTES);
    run.advance(CHUNK_FAST_MS + 1); // a slow chunk: size must not double
    first.resolve({ ok: true, received: INITIAL_CHUNK_BYTES });

    const second = await next();
    expect(second.path).toBe(
      `/agents/apollo/app-chat/attachments/att1/data?offset=${String(INITIAL_CHUNK_BYTES)}`,
    );
    expect((second.init?.body as Blob).size).toBe(10);
    second.resolve({ ok: true, received: size });

    const complete = await next();
    expect(complete.path).toBe(
      "/agents/apollo/app-chat/attachments/att1/complete",
    );
    complete.resolve({ attachment: { ...DONE, size } });

    await expect(handle.result).resolves.toEqual({ ...DONE, size });
    expect(run.progress).toEqual([
      [0, size],
      [INITIAL_CHUNK_BYTES, size],
      [size, size],
    ]);
    expect(run.states).toEqual(["uploading"]);
  });

  it("doubles the chunk after a fast success and halves it after a failure", async () => {
    const { http, next } = scriptedHttp();
    const size = MAX_CHUNK_UPLOAD_BYTES * 4;
    const { handle, run } = start(http, size);
    (await next()).resolve({ id: "att1" });

    const first = await next();
    expect((first.init?.body as Blob).size).toBe(INITIAL_CHUNK_BYTES);
    first.resolve({ ok: true }); // instant: doubles

    const second = await next();
    expect((second.init?.body as Blob).size).toBe(INITIAL_CHUNK_BYTES * 2);
    second.reject(new TypeError("network down")); // halves and parks

    await settle();
    expect(run.states).toEqual(["uploading", "waiting"]);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(RETRY_BASE_MS);

    const probe = await next();
    expect(probe.path).toBe("/agents/apollo/app-chat/attachments/att1/status");
    probe.resolve({ received: INITIAL_CHUNK_BYTES, size, finalized: false });

    const third = await next();
    expect((third.init?.body as Blob).size).toBe(INITIAL_CHUNK_BYTES);
    expect(third.path).toContain(`offset=${String(INITIAL_CHUNK_BYTES)}`);
    handle.abort();
    await expect(handle.result).rejects.toThrow("aborted");
  });

  it("never shrinks below the floor", async () => {
    const { http, next } = scriptedHttp();
    const { handle } = start(http, MIN_CHUNK_BYTES * 8);
    (await next()).resolve({ id: "att1" });
    for (let failure = 0; failure < 4; failure += 1) {
      (await next()).reject(new TypeError("down"));
      await settle();
      await vi.advanceTimersToNextTimerAsync();
      (await next()).resolve({
        received: 0,
        size: MIN_CHUNK_BYTES * 8,
        finalized: false,
      });
    }
    const put = await next();
    expect((put.init?.body as Blob).size).toBe(MIN_CHUNK_BYTES);
    handle.abort();
    await expect(handle.result).rejects.toThrow("aborted");
  });

  it("resyncs to the server's received on a 409 without counting a failure", async () => {
    const { http, next } = scriptedHttp();
    const size = INITIAL_CHUNK_BYTES * 2;
    const { handle, run } = start(http, size);
    (await next()).resolve({ id: "att1" });

    const first = await next();
    run.advance(CHUNK_FAST_MS + 1);
    first.reject(new ApiError(409, "offset mismatch"));

    const probe = await next();
    expect(probe.path).toBe("/agents/apollo/app-chat/attachments/att1/status");
    // The lost-response case: the server already has the whole first chunk.
    probe.resolve({ received: INITIAL_CHUNK_BYTES, size, finalized: false });

    const second = await next();
    expect(second.path).toContain(`offset=${String(INITIAL_CHUNK_BYTES)}`);
    second.resolve({ ok: true });
    (await next()).resolve({ attachment: { ...DONE, size } });

    await expect(handle.result).resolves.toEqual({ ...DONE, size });
    expect(run.states).toEqual(["uploading"]); // no waiting state on a resync
  });

  it("parks offline without timers and resumes on the online edge via the status probe", async () => {
    const { http, next } = scriptedHttp();
    const run = harness();
    const { handle } = start(http, INITIAL_CHUNK_BYTES, run);
    (await next()).resolve({ id: "att1" });

    const first = await next();
    run.setOnline(false);
    first.reject(new TypeError("connection lost"));

    await settle();
    expect(run.states).toEqual(["uploading", "waiting"]);
    expect(vi.getTimerCount()).toBe(0); // no backoff timer burns while offline

    run.setOnline(true);
    const probe = await next();
    probe.resolve({ received: 0, size: INITIAL_CHUNK_BYTES, finalized: false });
    const retry = await next();
    expect(retry.path).toContain("offset=0");
    expect(run.states).toEqual(["uploading", "waiting", "uploading"]);
    handle.abort();
    await expect(handle.result).rejects.toThrow("aborted");
  });

  it("rejects terminal outcomes without a single retry", async () => {
    const { http } = scriptedHttp();
    const blob = new Blob([new Uint8Array(1)]);
    const run = harness();
    const over = uploadAttachment(
      http,
      {
        agent: "apollo",
        blob,
        meta: { ...META, size: MAX_ATTACHMENT_BYTES + 1 },
      },
      run.deps,
      run.callbacks,
    );
    await expect(over.result).rejects.toMatchObject({ reason: "too_large" });

    const notFound = scriptedHttp();
    const old = start(notFound.http, 1);
    (await notFound.next()).reject(new ApiError(404, "not found"));
    await expect(old.handle.result).rejects.toMatchObject({
      reason: "unsupported_agent",
    });

    const badRequest = scriptedHttp();
    const bad = start(badRequest.http, 1);
    (await badRequest.next()).resolve({ id: "att1" });
    (await badRequest.next()).reject(new ApiError(400, "nope"));
    await expect(bad.handle.result).rejects.toMatchObject({ reason: "failed" });

    const mismatch = scriptedHttp();
    const short = start(mismatch.http, 1);
    (await mismatch.next()).resolve({ id: "att1" });
    (await mismatch.next()).resolve({ ok: true });
    (await mismatch.next()).reject(new ApiError(409, "size mismatch"));
    await expect(short.handle.result).rejects.toMatchObject({
      reason: "failed",
    });
  });

  it("aborting during a park clears the timer and rejects", async () => {
    const { http, next } = scriptedHttp();
    const { handle } = start(http, 1);
    (await next()).reject(new ApiError(503, "proxy down"));
    await settle();
    expect(vi.getTimerCount()).toBe(1);

    handle.abort();
    await expect(handle.result).rejects.toBeInstanceOf(UploadError);
    await expect(handle.result).rejects.toMatchObject({ reason: "aborted" });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("retries the create with growing backoff for retryable failures", async () => {
    const { http, next } = scriptedHttp();
    const { handle } = start(http, 1);
    (await next()).reject(new ApiError(502, "bad gateway"));
    await settle();
    await vi.advanceTimersByTimeAsync(RETRY_BASE_MS - 1);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    (await next()).reject(new ApiError(502, "bad gateway"));
    await settle();
    await vi.advanceTimersByTimeAsync(RETRY_BASE_MS * 2 - 1);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    (await next()).resolve({ id: "att1" });
    (await next()).resolve({ ok: true });
    (await next()).resolve({ attachment: DONE });
    await expect(handle.result).resolves.toEqual(DONE);
  });
});

describe("409 recovery under a broken link", () => {
  it("parks with backoff instead of busy-looping when the probe also fails", async () => {
    const { http, next } = scriptedHttp();
    const { handle, run } = start(http, INITIAL_CHUNK_BYTES);
    (await next()).resolve({ id: "att1" });
    (await next()).reject(new ApiError(409, "offset mismatch"));

    const probe = await next();
    expect(probe.path).toContain("/status");
    probe.reject(new TypeError("link died"));
    await settle();

    // No immediate re-PUT: the engine is parked on a backoff timer.
    expect(run.states).toEqual(["uploading", "waiting"]);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(RETRY_BASE_MS);
    (await next()).resolve({
      received: 0,
      size: INITIAL_CHUNK_BYTES,
      finalized: false,
    });
    const retry = await next();
    expect(retry.path).toContain("offset=0");
    handle.abort();
    await expect(handle.result).rejects.toThrow("aborted");
  });
});
