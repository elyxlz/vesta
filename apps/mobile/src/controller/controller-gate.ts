// Decides the controller's lifetime from connection presence and foreground.
// A background transition tears the controller down (no socket while suspended);
// returning to foreground while connected asks for a fresh controller (epoch bump).
export interface GateInput {
  connected: boolean; // a connection config exists
  foreground: boolean;
}
export type GateAction = "build" | "close" | "idle";

export function controllerGateAction(
  prev: GateInput,
  next: GateInput,
): GateAction {
  const want = (gate: GateInput) => gate.connected && gate.foreground;
  if (want(next) && !want(prev)) return "build";
  if (!want(next) && want(prev)) return "close";
  return "idle";
}
