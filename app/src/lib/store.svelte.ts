// ── Per-box operation state ────────────────────────────────────

export type BoxOperation = "idle" | "stopping" | "starting" | "authenticating" | "deleting" | "rebuilding" | "backing-up" | "restoring";

type BoxOpState = {
  operation: BoxOperation;
  error: string;
};

let boxStates = $state<Record<string, BoxOpState>>({});

export function getBoxOp(name: string): BoxOpState {
  return boxStates[name] ?? { operation: "idle", error: "" };
}

function setBoxOp(name: string, operation: BoxOperation, error = "") {
  boxStates[name] = { operation, error };
}

export function setBoxError(name: string, error: string) {
  const current = boxStates[name];
  if (current) {
    boxStates[name] = { ...current, error };
  } else {
    boxStates[name] = { operation: "idle", error };
  }
}

function clearBoxOp(name: string) {
  boxStates[name] = { operation: "idle", error: "" };
}

export function removeBoxState(name: string) {
  const { [name]: _, ...rest } = boxStates;
  boxStates = rest;
}

export function busyBoxName(): string | null {
  for (const [name, state] of Object.entries(boxStates)) {
    if (state.operation !== "idle") return name;
  }
  return null;
}

export async function withBoxOp(name: string, op: BoxOperation, fn: () => Promise<void>, fallback: string): Promise<void> {
  if (getBoxOp(name).operation !== "idle") return;
  setBoxError(name, "");
  setBoxOp(name, op);
  try {
    await fn();
  } catch (e: unknown) {
    setBoxError(name, (e as { message?: string })?.message || fallback);
  } finally {
    clearBoxOp(name);
  }
}
