import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { CHANNEL, PUSH_CHANNELS } from "./channels";

// The preload API is declared twice, here and as VestaNativeApi in the web app, and the two
// must stay field-for-field identical. The web declaration is a type, so its keys are read off
// the source text; the preload side is the object handed to contextBridge.
const exposed = vi.hoisted(() => ({
  api: null as Record<string, unknown> | null,
}));

vi.mock("electron", () => ({
  contextBridge: {
    exposeInMainWorld: (_name: string, api: Record<string, unknown>) => {
      exposed.api = api;
    },
  },
  ipcRenderer: {
    on: vi.fn(),
    removeListener: vi.fn(),
    invoke: vi.fn(),
    send: vi.fn(),
  },
}));

const WEB_TYPES = path.resolve(__dirname, "../../web/src/lib/native/types.ts");

function webApiKeys(): string[] {
  const source = fs.readFileSync(WEB_TYPES, "utf8");
  const block = /export interface VestaNativeApi \{([^}]*)\}/.exec(source)?.[1];
  if (block === undefined) throw new Error("VestaNativeApi not found");
  return [...block.matchAll(/^\s+(\w+)[(:]/gm)].map((match) => match[1] ?? "");
}

function channelKeys(source: string, pattern: RegExp): Set<string> {
  return new Set([...source.matchAll(pattern)].map((match) => match[1] ?? ""));
}

const read = (file: string) =>
  fs.readFileSync(path.resolve(__dirname, file), "utf8");

describe("preload api parity", () => {
  it("exposes exactly the fields VestaNativeApi declares", async () => {
    await import("./preload.js");
    expect(exposed.api).not.toBeNull();
    expect(Object.keys(exposed.api ?? {}).sort()).toEqual(webApiKeys().sort());
  });
});

// Channel names are read off the source text, since main.ts runs the app on import. Every channel
// the preload talks on must be handled by main or pushed from main, and nothing may be handled or
// pushed that the preload never listens on.
describe("ipc channel parity", () => {
  const preloadKeys = channelKeys(read("./preload.ts"), /CHANNEL\.(\w+)/g);
  const mainSource = read("./main.ts") + read("./window.ts");
  const handledKeys = channelKeys(
    mainSource,
    /ipcMain\.(?:handle|on)\(\s*CHANNEL\.(\w+)/g,
  );
  const pushedKeys = channelKeys(mainSource, /\.send\(\s*CHANNEL\.(\w+)/g);

  it("handles or pushes exactly the channels the preload uses", () => {
    expect([...new Set([...handledKeys, ...pushedKeys])].sort()).toEqual(
      [...preloadKeys].sort(),
    );
  });

  it("names every channel in the table and uses each one", () => {
    expect([...preloadKeys].sort()).toEqual(Object.keys(CHANNEL).sort());
  });

  it("lists exactly the pushed channels as push channels", () => {
    const pushed = [...pushedKeys].map(
      (key) => CHANNEL[key as keyof typeof CHANNEL],
    );
    expect(pushed.sort()).toEqual([...PUSH_CHANNELS].sort());
  });
});
