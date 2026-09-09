// Whether the composer's input should sit on its own row above the buttons. `width` is the
// text measured as a single line and `avail` the input's collapsed content width. Expand a hair
// before the last word would wrap, so the narrow field never shows two lines first; once
// expanded, hold until the text clearly fits again (hysteresis). A newline always expands.
export function composerExpandedNext(
  prev: boolean,
  value: string,
  avail: number,
  width: number,
): boolean {
  if (value.trim().length === 0) return false;
  if (value.includes("\n")) return true;
  if (avail <= 0) return prev;
  return prev ? width > avail - 24 : width > avail - 8;
}
