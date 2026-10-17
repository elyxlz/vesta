// Pure math for the slider. Every function is a worklet so the gestures run it on the UI thread;
// in node the directive is inert and the suite exercises the same code.

export interface SliderRange {
  min: number;
  max: number;
  step: number;
}

// A multiple of a decimal step carries binary noise (0.15000000000000002); values round to this.
const PRECISION = 1e6;

// The nearest value on the step grid that starts at `min`, held inside the range.
export function snapToStep(value: number, range: SliderRange): number {
  "worklet";
  const { min, max, step } = range;
  if (!(max > min)) return min;
  const stepped =
    step > 0 ? min + Math.round((value - min) / step) * step : value;
  const held = Math.min(max, Math.max(min, stepped));
  return Math.round(held * PRECISION) / PRECISION;
}

// The share of the track, from 0 to 1, that a value fills.
export function valueToFraction(value: number, range: SliderRange): number {
  "worklet";
  const { min, max } = range;
  if (!(max > min)) return 0;
  return Math.min(1, Math.max(0, (value - min) / (max - min)));
}

// The stepped value under a touch at `position` on a track that is `length` wide.
export function positionToValue(
  position: number,
  length: number,
  range: SliderRange,
): number {
  "worklet";
  if (!(length > 0)) return snapToStep(range.min, range);
  const fraction = Math.min(1, Math.max(0, position / length));
  return snapToStep(range.min + fraction * (range.max - range.min), range);
}

// The value one step above (1) or below (-1) a value.
export function stepValue(
  value: number,
  direction: 1 | -1,
  range: SliderRange,
): number {
  "worklet";
  return snapToStep(value + direction * range.step, range);
}
