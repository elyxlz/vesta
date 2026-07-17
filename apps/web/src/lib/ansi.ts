const ESC = "\x1b";
const BEL = "\x07";
const ANSI_RE = new RegExp(
  `${ESC}(?:\\[[0-9;:]*[a-zA-Z]|\\].*?(?:${BEL}|${ESC}\\\\)|\\([A-Z0-9])`,
  "g",
);

export function stripAnsi(text: string): string {
  // Strip to a fixpoint: removing one escape sequence can expose another
  // (e.g. "\x1b" + "\x1b[31m" + "[32m" -> "\x1b[32m"), so a single pass can
  // leave live ANSI codes in the output.
  let out = text;
  let previous;
  do {
    previous = out;
    out = out.replace(ANSI_RE, "");
  } while (out !== previous);
  return out;
}
