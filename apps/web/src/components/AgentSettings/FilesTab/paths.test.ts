import { describe, it, expect } from "vitest";
import {
  CONSTITUTION_PATH,
  friendlyLabel,
  isSimpleAllowed,
  MEMORY_PATH,
} from "./paths";

describe("isSimpleAllowed", () => {
  it("allows memory and constitution in simple mode", () => {
    expect(isSimpleAllowed(MEMORY_PATH)).toBe(true);
    expect(isSimpleAllowed(CONSTITUTION_PATH)).toBe(true);
  });

  it("allows skill markdown but not arbitrary files", () => {
    expect(isSimpleAllowed("/root/agent/skills/tasks/SKILL.md")).toBe(true);
    expect(isSimpleAllowed("/root/agent/data/foo.json")).toBe(false);
  });
});

describe("friendlyLabel", () => {
  it("labels memory and constitution by filename", () => {
    expect(friendlyLabel(MEMORY_PATH)).toBe("MEMORY.md");
    expect(friendlyLabel(CONSTITUTION_PATH)).toBe("constitution.md");
  });
});
