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
    const entry = useRestartPending.getState().pending["ada"];
    expect(entry.reasons).toEqual(["files"]);
    expect(entry.since).toBe(BOOT_T0);
  });

  it("clears the flag once the agent is observed booting with a newer start time", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T1 }]);
    expect(useRestartPending.getState().pending["ada"]).toBeUndefined();
  });

  it("keeps the flag while the agent has not restarted", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T0 }]);
    expect(useRestartPending.getState().pending["ada"].reasons).toEqual([
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
    expect(useRestartPending.getState().pending["ada"].since).toBe(BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T1 }]);
    expect(useRestartPending.getState().pending["ada"]).toBeUndefined();
  });

  it("ignores agents with no reported boot time", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending.getState().reconcile([{ name: "ada" }]);
    expect(useRestartPending.getState().pending["ada"].reasons).toEqual([
      "files",
    ]);
  });

  it("withdraws one reason without dropping another or losing the boot time", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending.getState().markPending("ada", "preempt-mode", BOOT_T0);
    useRestartPending.getState().clearReason("ada", "files");
    const entry = useRestartPending.getState().pending["ada"];
    expect(entry.reasons).toEqual(["preempt-mode"]);
    expect(entry.since).toBe(BOOT_T0);
  });

  it("keeps a known baseline when a later reason is flagged with no boot time", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending.getState().markPending("ada", "preempt-mode", undefined);
    expect(useRestartPending.getState().pending["ada"].since).toBe(BOOT_T0);
  });

  it("keeps a host-access flag across a restart, since a mount needs a recreate", () => {
    // A plain/crash restart reuses the container with the old mounts; only a recreate (the app
    // restart button) applies a new grant, so reconcile must not drop it on a boot change.
    useRestartPending.getState().markPending("ada", "host-access", BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T1 }]);
    expect(useRestartPending.getState().pending["ada"].reasons).toEqual([
      "host-access",
    ]);
  });

  it("clears restart-applied reasons but keeps host-access on the same restart", () => {
    useRestartPending.getState().markPending("ada", "files", BOOT_T0);
    useRestartPending.getState().markPending("ada", "host-access", BOOT_T0);
    useRestartPending
      .getState()
      .reconcile([{ name: "ada", startedAt: BOOT_T1 }]);
    expect(useRestartPending.getState().pending["ada"].reasons).toEqual([
      "host-access",
    ]);
  });
});

describe("migrateRestartPending", () => {
  it("carries v1 reason lists over with an unknown boot time", () => {
    const migrated = migrateRestartPending(
      { pending: { ada: ["files", "host-access"] } },
      1,
    );
    expect(migrated.pending["ada"]).toEqual({
      reasons: ["files", "host-access"],
      since: null,
    });
  });

  it("carries a v0 boolean flag over as the generic reason", () => {
    const migrated = migrateRestartPending({ pending: { ada: true } }, 0);
    expect(migrated.pending["ada"]).toEqual({
      reasons: ["settings"],
      since: null,
    });
  });

  it("drops a malformed v1 value that is not an array of known reasons", () => {
    const migrated = migrateRestartPending(
      { pending: { ada: "files", bob: ["files", "bogus"] } },
      1,
    );
    expect(migrated.pending["ada"]).toBeUndefined();
    expect(migrated.pending["bob"]).toEqual({
      reasons: ["files"],
      since: null,
    });
  });
});
