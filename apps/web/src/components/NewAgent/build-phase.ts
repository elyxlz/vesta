import type { BuildPhase } from "@vesta/core";

// Coarse, ordered stages of first-time agent creation reported by vestad while the create POST is in
// flight (core owns the type). The image step (`pulling` on a release build, `building` from a local
// checkout) is the dominant wait.
const BUILD_PHASE_MESSAGES: Record<BuildPhase, string> = {
  pulling: "downloading the agent image...",
  building: "building the agent image...",
  preparing: "preparing agent code...",
  creating: "creating the container...",
  starting: "starting up...",
};

/// Map a build phase to an honest, lowercase status line. A null phase (the
/// create has not reported yet, or has already settled) falls back to a neutral
/// line rather than a fabricated near-done claim.
export function buildPhaseMessage(phase: BuildPhase | null): string {
  return phase === null ? "setting things up..." : BUILD_PHASE_MESSAGES[phase];
}
