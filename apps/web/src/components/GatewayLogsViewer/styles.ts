import type { CSSProperties } from "react";

export const GatewayLogsViewerStyles: Record<string, CSSProperties> = {
  scroll: {
    flex: 1,
    minHeight: 0,
    overflow: "auto",
    padding: "12px 14px",
    borderRadius: 8,
    background: "var(--muted)",
    fontFamily: "var(--font-mono, monospace)",
    fontSize: 12,
    lineHeight: 1.5,
    // Don't wrap: wrapping re-flows every line on each resize frame (visible lag on
    // a large dialog full of logs). Long lines scroll horizontally instead.
    whiteSpace: "pre",
    color: "var(--foreground)",
  },
  line: {
    color: "var(--foreground)",
    width: "max-content",
    minWidth: "100%",
  },
  empty: {
    color: "var(--muted-foreground)",
  },
};
