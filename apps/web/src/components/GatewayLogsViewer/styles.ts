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
  timestamp: {
    color: "var(--muted-foreground)",
  },
  level: {
    fontWeight: 600,
  },
  empty: {
    color: "var(--muted-foreground)",
  },
};

// Per-level colors for the log level token. Tuned to read on the muted background
// in both themes; INFO stays neutral so warnings/errors stand out.
export const LogLevelColors: Record<string, string> = {
  ERROR: "#f87171",
  WARN: "#fbbf24",
  INFO: "#34d399",
  DEBUG: "var(--muted-foreground)",
  TRACE: "var(--muted-foreground)",
};
