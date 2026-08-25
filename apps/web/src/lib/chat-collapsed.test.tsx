import { beforeEach, describe, expect, it } from "vitest";
import { getChatCollapsed, setChatCollapsed } from "./chat-collapsed";

describe("chat-collapsed persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to expanded", () => {
    expect(getChatCollapsed("ada")).toBe(false);
  });

  it("remembers a collapse per agent", () => {
    setChatCollapsed("ada", true);
    expect(getChatCollapsed("ada")).toBe(true);
    expect(getChatCollapsed("bob")).toBe(false);
  });

  it("expanding clears the stored key", () => {
    setChatCollapsed("ada", true);
    setChatCollapsed("ada", false);
    expect(getChatCollapsed("ada")).toBe(false);
    expect(localStorage.length).toBe(0);
  });
});
