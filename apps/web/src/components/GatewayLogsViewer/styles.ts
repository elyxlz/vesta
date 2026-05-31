import type { CSSProperties } from "react";

export const GatewayLogsViewerStyles: Record<string, CSSProperties> = {
  scroll: {
    height: "55vh",
    overflowY: "auto",
    padding: "12px 14px",
    borderRadius: 8,
    background: "var(--muted)",
    fontFamily: "var(--font-mono, monospace)",
    fontSize: 12,
    lineHeight: 1.5,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    color: "var(--foreground)",
  },
  line: {
    color: "var(--foreground)",
  },
  empty: {
    color: "var(--muted-foreground)",
  },
};
