import { describe, expect, it } from "vitest";
import { currentRoom } from "./current-room";

// The router hands the matched params from the root down to the leaf, so the reporter reads the
// first match that names a conversation.
describe("currentRoom", () => {
  it.each([
    { name: "the roster", matched: [{}], expected: null },
    {
      name: "an agent page",
      matched: [{}, { name: "luna" }, {}],
      expected: "dm:luna",
    },
    {
      name: "an agent subpage",
      matched: [{}, { name: "luna" }, { name: "luna" }],
      expected: "dm:luna",
    },
    {
      name: "a room route",
      matched: [{}, { roomId: "grp-trip" }],
      expected: "grp-trip",
    },
  ])("reports $expected on $name", ({ matched, expected }) => {
    expect(currentRoom(matched)).toBe(expected);
  });
});
