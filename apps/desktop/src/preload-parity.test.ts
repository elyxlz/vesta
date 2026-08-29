import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";

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

describe("preload api parity", () => {
  it("exposes exactly the fields VestaNativeApi declares", async () => {
    await import("./preload.js");
    expect(exposed.api).not.toBeNull();
    expect(Object.keys(exposed.api ?? {}).sort()).toEqual(webApiKeys().sort());
  });
});
