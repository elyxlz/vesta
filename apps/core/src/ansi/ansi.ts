// The single ANSI/SGR parser: web and mobile both drive their log surfaces off this.
// Output is platform-neutral (segments of text + a style bag); each app resolves colors
// against its own palette and renders spans however it likes. No DOM, no React, no RN.

const ESC = "\x1b"
const BEL = "\x07"

export type AnsiColor = { kind: "palette"; index: number } | { kind: "rgb"; value: string }

export interface AnsiStyle {
  foreground?: AnsiColor
  background?: AnsiColor
  bold?: boolean
  dim?: boolean
  italic?: boolean
  underline?: boolean
  strikethrough?: boolean
  inverse?: boolean
  hidden?: boolean
}

export interface AnsiSpan {
  text: string
  style: AnsiStyle
}

type AnsiFlag = "bold" | "dim" | "italic" | "underline" | "strikethrough" | "inverse" | "hidden"

const ENABLED_STYLE_FLAGS: Partial<Record<number, AnsiFlag>> = {
  1: "bold",
  2: "dim",
  3: "italic",
  4: "underline",
  7: "inverse",
  8: "hidden",
  9: "strikethrough",
  21: "underline",
}

// CSI, OSC (BEL or ST terminated), single-shot two-byte, and character-set escapes.
// stripAnsi runs to a fixpoint: removing one sequence can expose another it left behind.
const ANSI_RE = new RegExp(
  `${ESC}(?:\\[[0-9;:]*[a-zA-Z]|\\].*?(?:${BEL}|${ESC}\\\\)|\\([A-Z0-9])`,
  "g",
)

// CSI, OSC, character-set, and two-byte escape sequences. SGR (`...m`) is interpreted
// below; the other terminal controls are removed from display.
const ANSI_CONTROL_RE = new RegExp(
  `(?:${ESC}\\[|\\u009b)([0-?]*)([ -/]*)([@-~])|${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)|${ESC}[()][A-Z0-9]|${ESC}[@-_]`,
  "g",
)

export function stripAnsi(text: string): string {
  let out = text
  let previous
  do {
    previous = out
    out = out.replace(ANSI_RE, "")
  } while (out !== previous)
  return out
}

function colorIndex(code: number): number | null {
  if (code >= 30 && code <= 37) return code - 30
  if (code >= 90 && code <= 97) return code - 90 + 8
  if (code >= 40 && code <= 47) return code - 40
  if (code >= 100 && code <= 107) return code - 100 + 8
  return null
}

function byte(value: number): number {
  return Math.max(0, Math.min(255, Math.round(value)))
}

function rgb(red: number, green: number, blue: number): string {
  return `rgb(${[red, green, blue].join(", ")})`
}

function extendedColor(
  parameters: number[],
  index: number,
): { color?: AnsiColor; consumed: number } {
  const mode = parameters[index + 1]
  const paletteIndex = parameters[index + 2]
  if (mode === 5 && paletteIndex !== undefined) {
    return { color: { kind: "palette", index: byte(paletteIndex) }, consumed: 2 }
  }
  const red = parameters[index + 2]
  const green = parameters[index + 3]
  const blue = parameters[index + 4]
  if (mode === 2 && red !== undefined && green !== undefined && blue !== undefined) {
    return {
      color: { kind: "rgb", value: rgb(byte(red), byte(green), byte(blue)) },
      consumed: 4,
    }
  }
  return { consumed: 0 }
}

function sgrParameters(value: string): number[] {
  if (!value) return [0]
  return value
    .split(/[;:]/)
    .filter((part) => part !== "")
    .map(Number)
    .filter(Number.isFinite)
}

function applyPaletteColor(style: AnsiStyle, code: number): void {
  const paletteIndex = colorIndex(code)
  if (paletteIndex === null) return

  const color: AnsiColor = { kind: "palette", index: paletteIndex }
  if ((code >= 40 && code <= 47) || code >= 100) {
    style.background = color
  } else {
    style.foreground = color
  }
}

function applySgr(current: AnsiStyle, sequence: string): AnsiStyle {
  let style = { ...current }
  const parameters = sgrParameters(sequence)
  for (let index = 0; index < parameters.length; index += 1) {
    const code = parameters[index]
    if (code === undefined) continue
    if (code === 0) {
      style = {}
      continue
    }

    const enabledFlag = ENABLED_STYLE_FLAGS[code]
    if (enabledFlag) {
      style[enabledFlag] = true
      continue
    }
    if (code === 22) {
      delete style.bold
      delete style.dim
      continue
    }
    if (code === 23) {
      delete style.italic
      continue
    }
    if (code === 24) {
      delete style.underline
      continue
    }
    if (code === 27) {
      delete style.inverse
      continue
    }
    if (code === 28) {
      delete style.hidden
      continue
    }
    if (code === 29) {
      delete style.strikethrough
      continue
    }
    if (code === 39) {
      delete style.foreground
      continue
    }
    if (code === 49) {
      delete style.background
      continue
    }
    if (code === 38 || code === 48) {
      const result = extendedColor(parameters, index)
      if (result.color) {
        if (code === 38) style.foreground = result.color
        else style.background = result.color
      }
      index += result.consumed
      continue
    }
    applyPaletteColor(style, code)
  }
  return style
}

export function parseAnsi(value: string): AnsiSpan[] {
  const spans: AnsiSpan[] = []
  let style: AnsiStyle = {}
  let offset = 0
  ANSI_CONTROL_RE.lastIndex = 0

  for (const match of value.matchAll(ANSI_CONTROL_RE)) {
    const start = match.index
    if (start > offset) {
      spans.push({ text: value.slice(offset, start), style: { ...style } })
    }
    const [, parameters, intermediates, command] = match
    if (command === "m" && !intermediates) {
      style = applySgr(style, parameters ?? "")
    }
    offset = start + match[0].length
  }

  if (offset < value.length) {
    spans.push({ text: value.slice(offset), style: { ...style } })
  }
  return spans
}

// Resolve an AnsiColor to a CSS color string against a caller-supplied 16-entry base
// palette (the 8 standard + 8 bright names). 256-color and grayscale are computed.
export function resolveAnsiColor(color: AnsiColor, basePalette: readonly string[]): string {
  if (color.kind === "rgb") return color.value
  if (color.index < 16) {
    return basePalette[color.index] ?? basePalette[7] ?? "#000000"
  }
  if (color.index < 232) {
    const index = color.index - 16
    const values = [0, 95, 135, 175, 215, 255]
    const red = values[Math.floor(index / 36)] ?? 0
    const green = values[Math.floor((index % 36) / 6)] ?? 0
    const blue = values[index % 6] ?? 0
    return rgb(red, green, blue)
  }
  const gray = 8 + (color.index - 232) * 10
  return rgb(gray, gray, gray)
}
