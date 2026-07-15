const ESC = "\x1b";
const BEL = "\x07";
const ANSI_RE = new RegExp(
  `${ESC}(?:\\[[0-9;:]*[a-zA-Z]|\\].*?(?:${BEL}|${ESC}\\\\)|\\([A-Z0-9])`,
  "g",
);

type AnsiColor =
  { kind: "palette"; index: number } | { kind: "rgb"; value: string };

interface AnsiStyle {
  foreground?: AnsiColor;
  background?: AnsiColor;
  bold?: boolean;
  dim?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikethrough?: boolean;
  inverse?: boolean;
  hidden?: boolean;
}

interface AnsiSpan {
  text: string;
  style: AnsiStyle;
}

const ANSI_PALETTE = [
  "var(--ansi-black)",
  "var(--ansi-red)",
  "var(--ansi-green)",
  "var(--ansi-yellow)",
  "var(--ansi-blue)",
  "var(--ansi-magenta)",
  "var(--ansi-cyan)",
  "var(--ansi-white)",
  "var(--ansi-bright-black)",
  "var(--ansi-bright-red)",
  "var(--ansi-bright-green)",
  "var(--ansi-bright-yellow)",
  "var(--ansi-bright-blue)",
  "var(--ansi-bright-magenta)",
  "var(--ansi-bright-cyan)",
  "var(--ansi-bright-white)",
] as const;

// CSI, OSC, character-set, and two-byte escape sequences. SGR (`...m`) is
// interpreted below; the other terminal controls are removed from display.
const ANSI_CONTROL_RE =
  // eslint-disable-next-line no-control-regex
  /(?:\x1b\[|\u009b)([0-?]*)([ -/]*)([@-~])|\x1b\][\s\S]*?(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[@-_]/g;

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

function colorIndex(code: number): number | null {
  if (code >= 30 && code <= 37) return code - 30;
  if (code >= 90 && code <= 97) return code - 90 + 8;
  if (code >= 40 && code <= 47) return code - 40;
  if (code >= 100 && code <= 107) return code - 100 + 8;
  return null;
}

function byte(value: number): number {
  return Math.max(0, Math.min(255, Math.round(value)));
}

function extendedColor(
  parameters: number[],
  index: number,
): { color?: AnsiColor; consumed: number } {
  const mode = parameters[index + 1];
  const paletteIndex = parameters[index + 2];
  if (mode === 5 && paletteIndex !== undefined) {
    return {
      color: { kind: "palette", index: byte(paletteIndex) },
      consumed: 2,
    };
  }
  if (
    mode === 2 &&
    parameters[index + 2] !== undefined &&
    parameters[index + 3] !== undefined &&
    parameters[index + 4] !== undefined
  ) {
    return {
      color: {
        kind: "rgb",
        value: `rgb(${byte(parameters[index + 2])}, ${byte(parameters[index + 3])}, ${byte(parameters[index + 4])})`,
      },
      consumed: 4,
    };
  }
  return { consumed: 0 };
}

function sgrParameters(value: string): number[] {
  if (!value) return [0];
  return value
    .split(/[;:]/)
    .filter((part) => part !== "")
    .map(Number)
    .filter(Number.isFinite);
}

function applySgr(current: AnsiStyle, sequence: string): AnsiStyle {
  let style = { ...current };
  const parameters = sgrParameters(sequence);
  for (let index = 0; index < parameters.length; index += 1) {
    const code = parameters[index];
    if (code === undefined) continue;
    if (code === 0) {
      style = {};
    } else if (code === 1) {
      style.bold = true;
    } else if (code === 2) {
      style.dim = true;
    } else if (code === 3) {
      style.italic = true;
    } else if (code === 4 || code === 21) {
      style.underline = true;
    } else if (code === 7) {
      style.inverse = true;
    } else if (code === 8) {
      style.hidden = true;
    } else if (code === 9) {
      style.strikethrough = true;
    } else if (code === 22) {
      delete style.bold;
      delete style.dim;
    } else if (code === 23) {
      delete style.italic;
    } else if (code === 24) {
      delete style.underline;
    } else if (code === 27) {
      delete style.inverse;
    } else if (code === 28) {
      delete style.hidden;
    } else if (code === 29) {
      delete style.strikethrough;
    } else if (code === 39) {
      delete style.foreground;
    } else if (code === 49) {
      delete style.background;
    } else if (code === 38 || code === 48) {
      const result = extendedColor(parameters, index);
      if (result.color) {
        if (code === 38) style.foreground = result.color;
        else style.background = result.color;
      }
      index += result.consumed;
    } else {
      const paletteIndex = colorIndex(code);
      if (paletteIndex !== null) {
        const color: AnsiColor = { kind: "palette", index: paletteIndex };
        if ((code >= 40 && code <= 47) || code >= 100) {
          style.background = color;
        } else {
          style.foreground = color;
        }
      }
    }
  }
  return style;
}

function parseAnsi(value: string): AnsiSpan[] {
  const spans: AnsiSpan[] = [];
  let style: AnsiStyle = {};
  let offset = 0;
  ANSI_CONTROL_RE.lastIndex = 0;

  for (const match of value.matchAll(ANSI_CONTROL_RE)) {
    const start = match.index ?? 0;
    if (start > offset) {
      spans.push({ text: value.slice(offset, start), style: { ...style } });
    }
    const [, parameters, intermediates, command] = match;
    if (command === "m" && !intermediates) {
      style = applySgr(style, parameters ?? "");
    }
    offset = start + match[0].length;
  }

  if (offset < value.length) {
    spans.push({ text: value.slice(offset), style: { ...style } });
  }
  return spans;
}

function resolveColor(color: AnsiColor): string {
  if (color.kind === "rgb") return color.value;
  if (color.index < 16) {
    return ANSI_PALETTE[color.index] ?? ANSI_PALETTE[7];
  }
  if (color.index < 232) {
    const index = color.index - 16;
    const values = [0, 95, 135, 175, 215, 255];
    const red = values[Math.floor(index / 36)] ?? 0;
    const green = values[Math.floor((index % 36) / 6)] ?? 0;
    const blue = values[index % 6] ?? 0;
    return `rgb(${red}, ${green}, ${blue})`;
  }
  const gray = 8 + (color.index - 232) * 10;
  return `rgb(${gray}, ${gray}, ${gray})`;
}

function styleDeclarations(style: AnsiStyle): string[] {
  let foreground = style.foreground
    ? resolveColor(style.foreground)
    : undefined;
  let background = style.background
    ? resolveColor(style.background)
    : undefined;

  if (style.inverse) {
    const previousForeground = foreground;
    foreground = background ?? "var(--ansi-black)";
    background = previousForeground ?? "var(--ansi-white)";
  }

  const declarations: string[] = [];
  if (foreground) declarations.push(`color:${foreground}`);
  if (background) declarations.push(`background-color:${background}`);
  if (style.bold) declarations.push("font-weight:700");
  if (style.dim) declarations.push("opacity:0.62");
  if (style.italic) declarations.push("font-style:italic");
  if (style.hidden) declarations.push("visibility:hidden");
  const decorations = [
    style.underline ? "underline" : "",
    style.strikethrough ? "line-through" : "",
  ].filter(Boolean);
  if (decorations.length > 0) {
    declarations.push(`text-decoration:${decorations.join(" ")}`);
  }
  return declarations;
}

/** Convert portable terminal styling to safe spans around caller-rendered text. */
export function renderAnsiHtml(
  value: string,
  renderText: (text: string) => string,
): string {
  return parseAnsi(value)
    .map((span) => {
      const html = renderText(span.text);
      const declarations = styleDeclarations(span.style);
      return declarations.length > 0
        ? `<span style="${declarations.join(";")}">${html}</span>`
        : html;
    })
    .join("");
}
