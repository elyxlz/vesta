import type { ASTNode } from "react-native-markdown-display";

export function isFinalMarkdownNode(
  node: ASTNode,
  parentNodes: ASTNode[],
): boolean {
  let child = node;
  for (const parent of parentNodes) {
    if (parent.children[parent.children.length - 1]?.key !== child.key) {
      return false;
    }
    child = parent;
  }
  return parentNodes[parentNodes.length - 1]?.type === "body";
}

export function isSameCalendarDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

export function chatDateLabel(timestamp: string | null): string {
  if (!timestamp) return "Earlier";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Earlier";
  const today = new Date();
  if (isSameCalendarDay(date, today)) return "Today";

  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (isSameCalendarDay(date, yesterday)) return "Yesterday";

  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: date.getFullYear() === today.getFullYear() ? undefined : "numeric",
  });
}

export type MarkdownLinkOpener = "in-app-browser" | "system" | "unsupported";

export interface MarkdownLinkTarget {
  url: string;
  opener: MarkdownLinkOpener;
}

export function resolveMarkdownLink(href: string): MarkdownLinkTarget {
  const trimmedHref = href.trim();
  const url = /^[a-z][a-z\d+.-]*:/i.test(trimmedHref)
    ? trimmedHref
    : `https://${trimmedHref.replace(/^\/+/, "")}`;
  const opener = /^https?:/i.test(url)
    ? "in-app-browser"
    : /^(mailto|tel|sms):/i.test(url)
      ? "system"
      : "unsupported";
  return { url, opener };
}
