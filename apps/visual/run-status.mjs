import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { atomicWriteFile, storeDirectory } from "./store.mjs";

// Each runner is its own process, so each publishes its own phase file and the
// gallery reads them all: two runners never overwrite each other's status. A
// "capturing" entry a hard-killed run left behind goes stale after the cutoff
// instead of showing a phantom run forever.
export const STALE_CAPTURING_MS = 45 * 60 * 1000;
const STATUS_FILE = /^run-status-([a-z-]+)\.json$/;

export function runStatusPath(runner, directory = storeDirectory) {
  return path.join(directory, `run-status-${runner}.json`);
}

export async function publishRunStatus(state, options, directory = storeDirectory) {
  if (!options.runner) throw new Error("A run status needs its runner.");
  const status = {
    state,
    runner: options.runner,
    message: options.message ?? "",
    detail: options.detail ?? "",
    startedAt: options.startedAt ?? null,
    updatedAt: new Date().toISOString(),
  };
  await atomicWriteFile(runStatusPath(options.runner, directory), `${JSON.stringify(status)}\n`);
}

// Drops stale capturing entries and orders newest first.
export function liveStatuses(statuses, now) {
  return statuses
    .filter(
      (status) =>
        status?.updatedAt &&
        !(status.state === "capturing" && now - Date.parse(status.updatedAt) > STALE_CAPTURING_MS),
    )
    .sort((left, right) => (left.updatedAt < right.updatedAt ? 1 : -1));
}

export async function currentRunStatus(directory = storeDirectory) {
  const names = await readdir(directory).catch(() => []);
  const statuses = [];
  for (const name of names) {
    if (!STATUS_FILE.test(name)) continue;
    const parsed = await readFile(path.join(directory, name), "utf8")
      .then((raw) => JSON.parse(raw))
      .catch(() => null);
    if (parsed) statuses.push(parsed);
  }
  return { statuses: liveStatuses(statuses, Date.now()) };
}
