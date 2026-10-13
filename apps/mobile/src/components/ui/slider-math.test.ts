import { describe, expect, it } from "vitest";
import {
  positionToValue,
  snapToStep,
  stepValue,
  valueToFraction,
} from "./slider-math";

const UNIT = { min: 0, max: 1, step: 0.05 };
const MILLIS = { min: 500, max: 10000, step: 500 };

describe("snapToStep", () => {
  it.each([
    [0.151, UNIT, 0.15],
    [0.174, UNIT, 0.15],
    [0.176, UNIT, 0.2],
    [1240, MILLIS, 1000],
    [1260, MILLIS, 1500],
    [0.34, { min: 0.1, max: 0.9, step: 0.2 }, 0.3],
  ])("moves %s to the nearest step", (value, range, expected) => {
    expect(snapToStep(value, range)).toBe(expected);
  });

  it.each([
    [-3, UNIT, 0],
    [7, UNIT, 1],
    [120, MILLIS, 500],
    [99999, MILLIS, 10000],
  ])("holds %s inside the range", (value, range, expected) => {
    expect(snapToStep(value, range)).toBe(expected);
  });

  it("removes the binary noise of a decimal step", () => {
    expect(snapToStep(0.15000000000000002, UNIT)).toBe(0.15);
    expect(snapToStep(0.3, { min: 0, max: 1, step: 0.1 })).toBe(0.3);
  });

  it("keeps the value when the step is zero", () => {
    expect(snapToStep(0.123, { min: 0, max: 1, step: 0 })).toBe(0.123);
  });

  it("answers the minimum for an empty range", () => {
    expect(snapToStep(4, { min: 2, max: 2, step: 1 })).toBe(2);
  });
});

describe("valueToFraction", () => {
  it.each([
    [0, UNIT, 0],
    [0.25, UNIT, 0.25],
    [1, UNIT, 1],
    [5250, MILLIS, 0.5],
  ])("places %s on the track", (value, range, expected) => {
    expect(valueToFraction(value, range)).toBe(expected);
  });

  it("holds a value outside the range at the ends of the track", () => {
    expect(valueToFraction(-1, UNIT)).toBe(0);
    expect(valueToFraction(2, UNIT)).toBe(1);
  });

  it("answers zero for an empty range", () => {
    expect(valueToFraction(2, { min: 2, max: 2, step: 1 })).toBe(0);
  });
});

describe("positionToValue", () => {
  it.each([
    [0, 0],
    [100, 0.5],
    [200, 1],
    [61, 0.3],
    [69, 0.35],
  ])("reads a touch at %s on a 200 wide track", (position, expected) => {
    expect(positionToValue(position, 200, UNIT)).toBe(expected);
  });

  it("holds a touch outside the track at its ends", () => {
    expect(positionToValue(-40, 200, UNIT)).toBe(0);
    expect(positionToValue(260, 200, UNIT)).toBe(1);
  });

  it("reads a range that does not start at zero", () => {
    expect(positionToValue(100, 200, MILLIS)).toBe(5500);
    expect(positionToValue(0, 200, MILLIS)).toBe(500);
  });

  it("answers the minimum before the track has a width", () => {
    expect(positionToValue(50, 0, MILLIS)).toBe(500);
  });
});

describe("stepValue", () => {
  it("moves one step up and one step down", () => {
    expect(stepValue(0.5, 1, UNIT)).toBe(0.55);
    expect(stepValue(0.5, -1, UNIT)).toBe(0.45);
    expect(stepValue(1500, 1, MILLIS)).toBe(2000);
  });

  it("stops at the ends of the range", () => {
    expect(stepValue(1, 1, UNIT)).toBe(1);
    expect(stepValue(0, -1, UNIT)).toBe(0);
  });
});
