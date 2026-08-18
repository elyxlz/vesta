import { readFile } from "node:fs/promises";
import path from "node:path";
import { atomicWriteFile, storeDirectory } from "./store.mjs";

// A capture runs in its own process, so its progress crosses to the gallery on disk:
// each phase is written here and /status.json serves whichever of the server's own
// state and the file is newer. A "capturing" entry a hard-killed run left behind goes
// stale after the cutoff instead of showing a phantom run forever.
export const runStatusPath = path.join(storeDirectory, "run-status.json");
export const STALE_CAPTURING_MS = 45 * 60 * 1000;

// The initial state carries the epoch, not boot time: a restarted server must not
// outrank the last phase an in-flight capture wrote to the file.
let serverStatus = {
  state: "ready",
  message: "Screenshots are up to date",
  detail: "",
  startedAt: null,
  runner: null,
  updatedAt: new Date(0).toISOString(),
};

export async function publishRunStatus(
  state,
  options = {},
  target = runStatusPath,
) {
  serverStatus = {
    state,
    message: options.message ?? "",
    detail: options.detail ?? "",
    startedAt: options.startedAt ?? null,
    runner: options.runner ?? null,
    updatedAt: new Date().toISOString(),
  };
  await atomicWriteFile(target, `${JSON.stringify(serverStatus)}\n`);
}

export function newerRunStatus(server, fileStatus, now) {
  if (!fileStatus?.updatedAt) return server;
  if (
    fileStatus.state === "capturing" &&
    now - Date.parse(fileStatus.updatedAt) > STALE_CAPTURING_MS
  ) {
    return server;
  }
  return fileStatus.updatedAt > server.updatedAt ? fileStatus : server;
}

export async function currentRunStatus(target = runStatusPath) {
  const fileStatus = await readFile(target, "utf8")
    .then((raw) => JSON.parse(raw))
    .catch(() => null);
  return newerRunStatus(serverStatus, fileStatus, Date.now());
}
