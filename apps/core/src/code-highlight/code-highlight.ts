import { createLowlight } from "lowlight";
import type { Element, ElementContent, Root } from "hast";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import diff from "highlight.js/lib/languages/diff";
import go from "highlight.js/lib/languages/go";
import ini from "highlight.js/lib/languages/ini";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

export type CodeTokenKind =
  | "plain"
  | "keyword"
  | "string"
  | "number"
  | "comment"
  | "function"
  | "type"
  | "variable"
  | "operator";

export interface CodeToken {
  text: string;
  kind: CodeTokenKind;
}

export interface HighlightedCode {
  language: string | null;
  lines: CodeToken[][];
}

type CodeColorToken =
  | "foreground"
  | "ansi-magenta"
  | "ansi-green"
  | "ansi-yellow"
  | "tertiary-foreground"
  | "ansi-blue"
  | "ansi-cyan"
  | "ansi-red"
  | "muted-foreground";

export const CODE_TOKEN_COLORS: Readonly<
  Record<CodeTokenKind, CodeColorToken>
> = {
  plain: "foreground",
  keyword: "ansi-magenta",
  string: "ansi-green",
  number: "ansi-yellow",
  comment: "tertiary-foreground",
  function: "ansi-blue",
  type: "ansi-cyan",
  variable: "ansi-red",
  operator: "muted-foreground",
};

export const HIGHLIGHT_MAX_CHARS = 20_000;

const lowlight = createLowlight({
  bash,
  css,
  diff,
  go,
  javascript,
  json,
  python,
  rust,
  sql,
  toml: ini,
  typescript,
  xml,
  yaml,
});

const ALIASES: Readonly<Record<string, string>> = {
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  py: "python",
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  yml: "yaml",
  rs: "rust",
  html: "xml",
  ini: "toml",
};

// highlight.js scope (hljs- prefix stripped, sub-scopes joined by ".") to kind;
// the full scope is tried first, then its first segment.
const SCOPE_KINDS: Readonly<Record<string, CodeTokenKind>> = {
  keyword: "keyword",
  literal: "keyword",
  "selector-tag": "keyword",
  name: "keyword",
  meta: "keyword",
  string: "string",
  regexp: "string",
  symbol: "string",
  addition: "string",
  number: "number",
  comment: "comment",
  doctag: "comment",
  quote: "comment",
  title: "function",
  "title.function_": "function",
  built_in: "function",
  section: "function",
  type: "type",
  "title.class_": "type",
  "title.class_.inherited__": "type",
  variable: "variable",
  "template-variable": "variable",
  attr: "variable",
  attribute: "variable",
  property: "variable",
  params: "variable",
  deletion: "variable",
  operator: "operator",
  punctuation: "operator",
};

function resolveLanguage(info: string | null): string | null {
  const word = info?.trim().split(/\s+/)[0]?.toLowerCase() ?? "";
  if (word === "") return null;
  const name = ALIASES[word] ?? word;
  return lowlight.registered(name) ? name : null;
}

function scopeKind(element: Element, inherited: CodeTokenKind): CodeTokenKind {
  const classes = element.properties.className;
  if (!Array.isArray(classes)) return inherited;
  const scope = classes.map((name) => name.replace(/^hljs-/, "")).join(".");
  const head = scope.split(".")[0] ?? "";
  return SCOPE_KINDS[scope] ?? SCOPE_KINDS[head] ?? inherited;
}

function pushText(
  lines: CodeToken[][],
  text: string,
  kind: CodeTokenKind,
): void {
  text.split("\n").forEach((part, index) => {
    if (index > 0) lines.push([]);
    if (part !== "") lines[lines.length - 1]?.push({ text: part, kind });
  });
}

function walk(
  nodes: ElementContent[],
  kind: CodeTokenKind,
  lines: CodeToken[][],
): void {
  for (const node of nodes) {
    if (node.type === "text") pushText(lines, node.value, kind);
    else if (node.type === "element")
      walk(node.children, scopeKind(node, kind), lines);
  }
}

function plainLines(code: string): CodeToken[][] {
  const lines: CodeToken[][] = [[]];
  pushText(lines, code, "plain");
  return lines;
}

export function highlightCode(
  code: string,
  info: string | null,
): HighlightedCode {
  const language = resolveLanguage(info);
  if (language === null || code.length > HIGHLIGHT_MAX_CHARS) {
    return { language, lines: plainLines(code) };
  }
  const tree: Root = lowlight.highlight(language, code);
  const lines: CodeToken[][] = [[]];
  walk(
    tree.children.filter((node) => node.type !== "doctype"),
    "plain",
    lines,
  );
  return { language, lines };
}
