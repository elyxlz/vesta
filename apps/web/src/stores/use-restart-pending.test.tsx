// Exercises the real persisted store, so it runs in the jsdom project (localStorage present) —
// hence .test.tsx despite having no JSX. The .test.ts (node) project has no localStorage.
import { beforeEach, describe, expect, it } from "vitest";

import {
  migrateRestartPending,
  useRestartPending,
} from "./use-restart-pending";

const BOOT_T0 = "2026-07-07T10:00:00Z";
const BOOT_T1 = "2026-07-07T11:00:00Z";

beforeEach(() => {
  localStorage.clear();
  useRestartPending.setState({ pending: {} });
});

describe("useRestartPending", () => {
  it("captures the agent's boot time when a change is flagged", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    const entry = useRestartPending.getState().pending.ada;
    expect(entry?.reasons).toEqual(["files"]);
    expect(entry?.since).toBe(BOOT_T0);
  });

  it("withdrawing the last reason drops the agent's entry entirely", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending.getState().markPending("ada", "host-access", BOOT_T0);
    useRestartPending.getState().clearReason("ada", "files");
    expect(useRestartPending.getState().pending.ada?.reasons).toEqual([
      "host-access",
    ]);
    useRestartPending.getState().clearReason("ada", "host-access");
    expect(useRestartPending.getState().pending.ada).toBeUndefined();
  });

  it("clears the flag once the agent is observed booting with a newer start time", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T1 }]);
    expect(useRestartPending.getState().pending.ada).toBeUndefined();
  });

  it("keeps the flag while the agent has not restarted", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T0 }]);
    expect(useRestartPending.getState().pending.ada?.reasons).toEqual([
      "files",
    ]);
  });

  it("adopts a baseline for a flag with no captured boot time, then clears on the next restart", () => {
    // Mirrors a flag carried over from before this fix shipped (since unknown).
    useRestartPending.setState({
      pending: { ada: { reasons: ["settings"], since: null } },
    });
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T0 }]);
    // First sighting only pins the baseline; the flag must survive.
    expect(useRestartPending.getState().pending.ada?.since).toBe(BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T1 }]);
    expect(useRestartPending.getState().pending.ada).toBeUndefined();
  });

  it("clears restart-applied reasons but keeps host-access across a recreate", () => {
    // A plain/crash restart reuses the container with the old mounts; only a
    // recreate (the app restart button) applies a new grant, so reconcile clears
    // the applied reasons but must not drop host-access on a boot change.
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending.getState().markPending("ada", "host-access", BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T1 }]);
    expect(useRestartPending.getState().pending.ada?.reasons).toEqual([
      "host-access",
    ]);
  });
});

describe("migrateRestartPending", () => {
  it.each<
    [
      string,
      unknown,
      number,
      ReturnType<typeof migrateRestartPending>["pending"],
    ]
  >([
    [
      "carries v1 reason lists over with an unknown boot time",
      { pending: { ada: ["files", "host-access"] } },
      1,
      { ada: { reasons: ["files", "host-access"], since: null } },
    ],
    [
      "carries a v0 boolean flag over as the generic reason",
      { pending: { ada: true } },
      0,
      { ada: { reasons: ["settings"], since: null } },
    ],
    [
      "drops a malformed v1 value, keeping only the known reasons",
      { pending: { ada: "files", bob: ["files", "bogus"] } },
      1,
      { bob: { reasons: ["files"], since: null } },
    ],
  ])("%s", (_name, persisted, version, expected) => {
    expect(migrateRestartPending(persisted, version).pending).toEqual(expected);
  });
});
