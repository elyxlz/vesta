import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { atomicWriteFile, storeDirectory } from "./store.mjs";

// Each runner is its own process, so each publishes its own phase file and the
// gallery reads them all: two runners never overwrite each other's status. The
// file carries the runner's pid, so a "capturing" entry whose process is gone
// (a hard-killed run) reads as stopped the moment the gallery looks.
const STATUS_FILE = /^run-status-([a-z-]+)\.json$/;

export function runStatusPath(runner, directory = storeDirectory) {
  return path.join(directory, `run-status-${runner}.json`);
}

export async function publishRunStatus(
  state,
  options,
  directory = storeDirectory,
) {
  if (!options.runner) throw new Error("A run status needs its runner.");
  const status = {
    state,
    runner: options.runner,
    message: options.message ?? "",
    detail: options.detail ?? "",
    startedAt: options.startedAt ?? null,
    updatedAt: new Date().toISOString(),
    pid: process.pid,
  };
  await atomicWriteFile(
    runStatusPath(options.runner, directory),
    `${JSON.stringify(status)}\n`,
  );
}

export function processAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === "EPERM";
  }
}

// A capturing entry whose runner process is gone becomes the error it is;
// entries are ordered newest first.
export function liveStatuses(statuses, isAlive = processAlive) {
  return statuses
    .filter((status) => status?.updatedAt)
    .map((status) =>
      status.state === "capturing" &&
      !(typeof status.pid === "number" && isAlive(status.pid))
        ? {
            ...status,
            state: "error",
            message: `${status.runner} capture stopped`,
            detail: "The runner exited before it finished.",
          }
        : status,
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
  return { statuses: liveStatuses(statuses) };
}
