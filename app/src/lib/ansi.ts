const ANSI_RE = /\x1b\[[0-9;]*[a-zA-Z]/g;

export function stripAnsi(text: string): string {
  return text.replace(ANSI_RE, "");
}

export interface ParsedLine {
  text: string;
  category: string | null;
}

const CATEGORY_RE = /^\[([A-Z_]+)\]\s*/;

export function parseLine(raw: string): ParsedLine {
  const clean = stripAnsi(raw);
  const match = clean.match(CATEGORY_RE);
  if (match) {
    return {
      text: clean.slice(match[0].length),
      category: match[1],
    };
  }
  return { text: clean, category: null };
}
