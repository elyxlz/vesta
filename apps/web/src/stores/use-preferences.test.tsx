import { beforeEach, describe, expect, it } from "vitest";
import {
  naturalPacingFor,
  setChatCollapsed,
  usePreferences,
} from "./use-preferences";

beforeEach(() => {
  localStorage.clear();
  usePreferences.setState({
    naturalPacingByAgent: {},
    chatCollapsed: [],
    lastAgent: null,
  });
});

describe("usePreferences", () => {
  it("defaults natural pacing on per agent", () => {
    expect(naturalPacingFor("ada")).toBe(true);
    usePreferences.getState().update({ naturalPacingByAgent: { ada: false } });
    expect(naturalPacingFor("ada")).toBe(false);
    expect(naturalPacingFor("ben")).toBe(true);
  });

  it("remembers a collapsed chat per agent and expands by removal", () => {
    setChatCollapsed("ada", true);
    setChatCollapsed("ben", true);
    expect(usePreferences.getState().chatCollapsed).toEqual(["ada", "ben"]);
    setChatCollapsed("ada", false);
    expect(usePreferences.getState().chatCollapsed).toEqual(["ben"]);
  });

  it("persists every preference under one key", () => {
    usePreferences
      .getState()
      .update({ lastAgent: "ada", shareLocation: false });
    const stored = localStorage.getItem("vesta-preferences");
    expect(stored).not.toBeNull();
    expect(JSON.parse(stored ?? "{}")).toMatchObject({
      state: { lastAgent: "ada", shareLocation: false },
    });
  });
});
