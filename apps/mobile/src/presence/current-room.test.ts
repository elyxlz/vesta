import { describe, expect, it } from "vitest";
import { currentRoom } from "./current-room";

describe("currentRoom", () => {
  const cases: {
    name: string;
    segments: string[];
    params: { name?: string; roomId?: string };
    expected: string | null;
  }[] = [
    { name: "home", segments: [], params: {}, expected: null },
    {
      name: "an agent page",
      segments: ["agent", "[name]"],
      params: { name: "luna" },
      expected: "dm:luna",
    },
    {
      name: "an agent subpage",
      segments: ["agent", "[name]", "settings"],
      params: { name: "luna" },
      expected: "dm:luna",
    },
    {
      name: "the room screen",
      segments: ["chat", "[roomId]"],
      params: { roomId: "grp-trip" },
      expected: "grp-trip",
    },
    {
      name: "a settings sheet",
      segments: ["settings"],
      params: {},
      expected: null,
    },
    {
      name: "an agent route before its param resolves",
      segments: ["agent"],
      params: {},
      expected: null,
    },
  ];

  for (const { name, segments, params, expected } of cases) {
    it(`reports ${expected ?? "no room"} on ${name}`, () => {
      expect(currentRoom(segments, params)).toBe(expected);
    });
  }
});
