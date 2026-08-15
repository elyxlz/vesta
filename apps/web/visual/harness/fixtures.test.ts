import { describe, expect, it } from "vitest";
import { parseServerFrame } from "@vesta/core";
import {
  HELLO,
  agentDelta,
  baseTree,
  snapshotFrame,
  startingAgent,
} from "./sync-fixtures";

describe("visual sync fixtures", () => {
  it("builds a hello the production parser accepts", () => {
    expect(parseServerFrame(JSON.stringify(HELLO)).kind).toBe("hello");
  });

  it("builds a snapshot the production parser accepts", () => {
    const frame = snapshotFrame(baseTree());
    expect(parseServerFrame(JSON.stringify(frame)).kind).toBe("snapshot");
  });

  it("builds an agent delta the production parser accepts", () => {
    const delta = agentDelta("luna", startingAgent("pulling"));
    expect(parseServerFrame(JSON.stringify(delta)).kind).toBe("delta");
  });
});
