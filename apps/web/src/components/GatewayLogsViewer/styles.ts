// Per-level colors for the log level token. Tuned to read on the dark terminal
// surface in both themes; INFO stays neutral so warnings/errors stand out.
export const LogLevelColors: Record<string, string> = {
  ERROR: "#f87171",
  WARN: "#fbbf24",
  INFO: "#34d399",
  DEBUG: "rgba(255,255,255,0.4)",
  TRACE: "rgba(255,255,255,0.4)",
};
