import {
  parseAnsi,
  resolveAnsiColor,
  type AnsiColor,
  type AnsiStyle,
} from "@vesta/core";

// Web resolves the 16 base ANSI colors to canonical token variables so the console
// tracks the active theme; 256-color and truecolor fall through to computed rgb().
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

function resolveColor(color: AnsiColor): string {
  return resolveAnsiColor(color, ANSI_PALETTE);
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
