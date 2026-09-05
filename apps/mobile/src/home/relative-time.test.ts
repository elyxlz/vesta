import { describe, expect, it } from "vitest";
import { relativeTime } from "./relative-time";

const NOW = Date.UTC(2026, 7, 1, 12, 0, 0);
const secondsAgo = (seconds: number) => (NOW - seconds * 1000) / 1000;

describe("relativeTime", () => {
  const cases: { name: string; seconds: number; expected: string }[] = [
    { name: "this minute", seconds: 20, expected: "now" },
    { name: "minutes", seconds: 9 * 60, expected: "9m" },
    { name: "the last minute of the hour", seconds: 59 * 60, expected: "59m" },
    { name: "hours", seconds: 5 * 3600, expected: "5h" },
    { name: "the last hour of the day", seconds: 23 * 3600, expected: "23h" },
    { name: "days", seconds: 3 * 86_400, expected: "3d" },
    { name: "the last day of the week", seconds: 6 * 86_400, expected: "6d" },
  ];

  for (const { name, seconds, expected } of cases) {
    it(`reads ${expected} for ${name}`, () => {
      expect(relativeTime(secondsAgo(seconds), NOW)).toBe(expected);
    });
  }

  it("falls back to a date past a week", () => {
    expect(relativeTime(secondsAgo(30 * 86_400), NOW)).toMatch(/\d/);
    expect(relativeTime(secondsAgo(30 * 86_400), NOW)).not.toMatch(/^\d+d$/);
  });
});
