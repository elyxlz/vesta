// Natural typing pacing, extracted from web's chat engine unchanged so web and mobile
// stream at the same rhythm. All timings in milliseconds. Math.random is injected so
// tests are deterministic; production passes the default.
export const PACING = {
  perChar: 25,
  min: 1500,
  max: 6000,
  variance: 0.2,
  flushThreshold: 3,
  maxMessages: 5000,
} as const

export function typingDelay(charCount: number, rng: () => number = Math.random): number {
  const raw = Math.min(PACING.min + PACING.perChar * charCount, PACING.max)
  const variance = Math.floor(raw * PACING.variance)
  return raw + Math.floor(rng() * variance * 2) - variance
}
