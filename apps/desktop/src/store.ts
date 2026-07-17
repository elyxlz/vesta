import { app } from "electron";
import fs from "node:fs/promises";
import path from "node:path";

function storePath(): string {
  return path.join(app.getPath("userData"), "connection.json");
}

export async function readConnection(): Promise<unknown> {
  let raw: string;
  try {
    raw = await fs.readFile(storePath(), "utf8");
  } catch {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function writeConnection(value: unknown): Promise<void> {
  const target = storePath();
  await fs.mkdir(path.dirname(target), { recursive: true });
  const tmp = `${target}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(value), "utf8");
  await fs.rename(tmp, target);
}

export async function clearConnection(): Promise<void> {
  await fs.rm(storePath(), { force: true });
}
