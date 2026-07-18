export const COMPOSER_INPUT_MIN_HEIGHT = 36;
export const COMPOSER_INPUT_MAX_HEIGHT = 180;
export const COMPOSER_SURFACE_PADDING = 4;
export const COMPOSER_BASE_HEIGHT =
  COMPOSER_INPUT_MIN_HEIGHT + COMPOSER_SURFACE_PADDING * 2;

export function clampComposerInputHeight(contentHeight: number): number {
  return Math.min(
    Math.max(contentHeight, COMPOSER_INPUT_MIN_HEIGHT),
    COMPOSER_INPUT_MAX_HEIGHT,
  );
}
