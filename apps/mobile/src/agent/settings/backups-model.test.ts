import { describe, expect, it } from "vitest";
import type { BackupInfo } from "@vesta/core";
import { backupTimeline, deletePrompt, restorePrompt } from "./backups-model";

const BASE: BackupInfo = {
  id: "snap-1",
  agent_name: "scout",
  backup_type: "periodic",
  created_at: "20260529-040001",
  size: 1024,
};

function pointOf(backup: Partial<BackupInfo>, gatewayVersion?: string) {
  const [point] = backupTimeline([{ ...BASE, ...backup }], gatewayVersion);
  if (!point) throw new Error("the timeline dropped the only snapshot");
  return point;
}

describe("backupTimeline", () => {
  it("orders the gateway's snapshots newest first", () => {
    const rows: BackupInfo[] = [
      { ...BASE, id: "middle", created_at: "20260201-040001" },
      { ...BASE, id: "oldest", created_at: "20260101-040001" },
      { ...BASE, id: "newest", created_at: "20260301-040001" },
    ];
    expect(backupTimeline(rows, "0.1.2").map((point) => point.id)).toEqual([
      "newest",
      "middle",
      "oldest",
    ]);
  });

  it("labels each kind rather than showing the wire enum", () => {
    expect(pointOf({ backup_type: "periodic" }, "0.1.2").label).toBe(
      "Automatic",
    );
    expect(pointOf({ backup_type: "manual" }, "0.1.2").label).toBe("Manual");
    expect(pointOf({ backup_type: "pre_restore" }, "0.1.2").label).toBe(
      "Safety",
    );
    expect(
      pointOf({ backup_type: "pre_update", from_version: "v0.1.1" }, "0.1.2")
        .label,
    ).toBe("Before update v0.1.1");
  });

  it("gives a kind it does not know a plain label", () => {
    const point = pointOf({ backup_type: "quarterly" }, "0.1.2");
    expect(point.kind).toBe("unknown");
    expect(point.label).toBe("Backup");
  });

  it("reads the version stamp the wire carries", () => {
    expect(pointOf({ vestad_version: "0.1.3" }, "0.1.2").eligibility).toBe(
      "newer",
    );
    expect(pointOf({ vestad_version: "0.1.1" }, "0.1.2").eligibility).toBe(
      "older",
    );
    expect(pointOf({ vestad_version: "0.1.2" }, "0.1.2").eligibility).toBe(
      "ok",
    );
  });

  it("clears every point while the roster reports no gateway version", () => {
    expect(pointOf({ vestad_version: "0.1.3" }, undefined).eligibility).toBe(
      "ok",
    );
  });
});

describe("restorePrompt", () => {
  it("says what a restore does before it runs", () => {
    const prompt = restorePrompt(pointOf({}, "0.1.2"), "scout", "0.1.2");
    expect(prompt.title).toBe("Restore this snapshot?");
    expect(prompt.action).toBe("Restore");
    expect(prompt.destructive).toBe(false);
    expect(prompt.body).toContain("safety snapshot");
    expect(prompt.body).toContain("returns scout to this point and restarts");
    expect(prompt.body).toContain("Automatic");
  });

  it("names both versions when the snapshot is older than the gateway", () => {
    const prompt = restorePrompt(
      pointOf({ vestad_version: "0.1.1" }, "0.1.2"),
      "scout",
      "0.1.2",
    );
    expect(prompt.body).toContain("vestad 0.1.1");
    expect(prompt.body).toContain("gateway runs 0.1.2");
    expect(prompt.body).toContain("migrations");
  });

  it("leaves the version line out when the snapshot matches the gateway", () => {
    const prompt = restorePrompt(
      pointOf({ vestad_version: "0.1.2" }, "0.1.2"),
      "scout",
      "0.1.2",
    );
    expect(prompt.body).not.toContain("migrations");
  });

  it("never refers to the agent as a thing", () => {
    const prompt = restorePrompt(pointOf({}, "0.1.2"), "scout", "0.1.2");
    expect(prompt.body).not.toMatch(/\bit\b|\bits\b/);
  });
});

describe("deletePrompt", () => {
  it("warns that a snapshot cannot come back", () => {
    const prompt = deletePrompt(pointOf({ backup_type: "manual" }, "0.1.2"));
    expect(prompt.title).toBe("Delete this snapshot?");
    expect(prompt.action).toBe("Delete");
    expect(prompt.destructive).toBe(true);
    expect(prompt.body).toContain("Manual");
    expect(prompt.body).toContain("cannot be undone");
  });
});
