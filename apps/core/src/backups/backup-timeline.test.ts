import { describe, expect, it } from "vitest"

import {
  buildBackupTimeline,
  parseBackupKind,
  type BackupKind,
  type BackupTimelineRow,
  type RestoreEligibility,
} from "./backup-timeline"

const BASE: BackupTimelineRow = {
  id: "snap-1",
  created_at: "20260529-040001",
  backup_type: "periodic",
  size: 1024,
}

describe("buildBackupTimeline ordering", () => {
  it("puts the newest snapshot first whatever order the gateway listed them in", () => {
    const rows: BackupTimelineRow[] = [
      { ...BASE, id: "middle", created_at: "20260201-040001" },
      { ...BASE, id: "oldest", created_at: "20260101-040001" },
      { ...BASE, id: "newest", created_at: "20260301-040001" },
    ]
    expect(buildBackupTimeline(rows, "0.1.2").map((point) => point.id)).toEqual([
      "newest",
      "middle",
      "oldest",
    ])
  })

  it("keeps input order for snapshots sharing a timestamp", () => {
    const rows: BackupTimelineRow[] = [
      { ...BASE, id: "first" },
      { ...BASE, id: "second" },
      { ...BASE, id: "third" },
    ]
    expect(buildBackupTimeline(rows, "0.1.2").map((point) => point.id)).toEqual([
      "first",
      "second",
      "third",
    ])
  })

  it("leaves the caller's array untouched", () => {
    const rows: BackupTimelineRow[] = [
      { ...BASE, id: "older", created_at: "20260101-040001" },
      { ...BASE, id: "newer", created_at: "20260301-040001" },
    ]
    buildBackupTimeline(rows, "0.1.2")
    expect(rows.map((row) => row.id)).toEqual(["older", "newer"])
  })

  it("returns nothing for an agent with no snapshots", () => {
    expect(buildBackupTimeline([], "0.1.2")).toEqual([])
  })
})

describe("backup labels", () => {
  const cases: [string, BackupKind, string | null | undefined, string][] = [
    ["names a scheduled snapshot for what made it", "periodic", null, "Automatic"],
    ["names a user-made snapshot", "manual", null, "Manual"],
    [
      "names the version a pre-update snapshot came from",
      "pre_update",
      "v0.1.2",
      "Before update v0.1.2",
    ],
    [
      "drops the version when a pre-update snapshot carries none",
      "pre_update",
      null,
      "Before update",
    ],
    [
      "drops the version when from_version is absent entirely",
      "pre_update",
      undefined,
      "Before update",
    ],
    ["drops the version when from_version is empty", "pre_update", "", "Before update"],
    ["names a pre-restore snapshot as the safety net it is", "pre_restore", null, "Safety"],
    ["falls back to a plain word for a kind it does not know", "unknown", null, "Backup"],
  ]

  it.each(cases)("%s", (_name, kind, fromVersion, label) => {
    const [point] = buildBackupTimeline(
      [{ ...BASE, backup_type: kind, from_version: fromVersion }],
      "0.1.2",
    )
    expect(point?.label).toBe(label)
    expect(point?.kind).toBe(kind)
  })

  it("never leaves the raw wire enum in a label", () => {
    const kinds: BackupKind[] = ["periodic", "manual", "pre_update", "pre_restore", "unknown"]
    const labels = buildBackupTimeline(
      kinds.map((kind) => ({ ...BASE, backup_type: kind })),
      "0.1.2",
    ).map((point) => point.label)
    for (const label of labels) expect(label).not.toContain("_")
  })
})

// The wire carries `backup_type` as a plain string and may add a kind without a client bump, so
// the parse belongs here rather than as an assertion in each app.
describe("parseBackupKind", () => {
  const cases: [string, BackupKind][] = [
    ["periodic", "periodic"],
    ["manual", "manual"],
    ["pre_update", "pre_update"],
    ["pre_restore", "pre_restore"],
    ["pre-update", "unknown"],
    ["quarterly", "unknown"],
    ["", "unknown"],
  ]

  it.each(cases)("reads %s as %s", (wire, kind) => {
    expect(parseBackupKind(wire)).toBe(kind)
  })

  it("still gives an unknown kind its version eligibility", () => {
    const [point] = buildBackupTimeline(
      [{ ...BASE, backup_type: parseBackupKind("quarterly"), vestad_version: "0.1.3" }],
      "0.1.2",
    )
    expect(point?.kind).toBe("unknown")
    expect(point?.eligibility).toBe("newer")
  })
})

describe("restore eligibility", () => {
  const cases: [string, string | null | undefined, string | null, RestoreEligibility][] = [
    ["clears a snapshot made by the running gateway", "0.1.2", "0.1.2", "ok"],
    ["flags older state, which restores behind a confirm", "0.1.1", "0.1.2", "older"],
    ["flags newer state, which the gateway refuses", "0.1.3", "0.1.2", "newer"],
    ["compares numerically rather than as text", "0.2.0", "0.10.0", "older"],
    ["compares each component numerically", "0.10.0", "0.2.0", "newer"],
    ["ignores a prerelease suffix", "0.1.2-beta.1", "0.1.2", "ok"],
    ["clears a legacy snapshot carrying no version", null, "0.1.2", "ok"],
    ["clears every snapshot when from_version is absent", undefined, "0.1.2", "ok"],
    ["clears a snapshot when the client knows no gateway version", "0.1.2", null, "ok"],
    ["fails open on a dev snapshot version", "dev", "0.1.2", "ok"],
    ["fails open on a dev gateway version", "0.1.2", "dev", "ok"],
    ["fails open on a v-prefixed version, which is not the stamp's shape", "v0.1.3", "0.1.2", "ok"],
  ]

  it.each(cases)("%s", (_name, vestadVersion, gatewayVersion, eligibility) => {
    const [point] = buildBackupTimeline(
      [{ ...BASE, vestad_version: vestadVersion }],
      gatewayVersion,
    )
    expect(point?.eligibility).toBe(eligibility)
  })

  // Shuffled, so a verdict that travelled with the wrong row through the sort shows up here.
  it("judges each snapshot against the same gateway", () => {
    const rows: BackupTimelineRow[] = [
      { ...BASE, id: "behind", created_at: "20260101-040001", vestad_version: "0.1.1" },
      { ...BASE, id: "ahead", created_at: "20260301-040001", vestad_version: "0.1.3" },
      { ...BASE, id: "level", created_at: "20260201-040001", vestad_version: "0.1.2" },
    ]
    const verdicts = buildBackupTimeline(rows, "0.1.2").map((point) => ({
      id: point.id,
      eligibility: point.eligibility,
    }))
    expect(verdicts).toEqual([
      { id: "ahead", eligibility: "newer" },
      { id: "level", eligibility: "ok" },
      { id: "behind", eligibility: "older" },
    ])
  })
})

describe("timeline points", () => {
  it("carries the fields a surface renders", () => {
    const [point] = buildBackupTimeline(
      [
        {
          id: "snap-7",
          created_at: "20260529-040001",
          backup_type: "pre_update",
          size: 4096,
          from_version: "v0.1.1",
          vestad_version: "0.1.1",
        },
      ],
      "0.1.2",
    )
    expect(point).toEqual({
      id: "snap-7",
      createdAt: "20260529-040001",
      kind: "pre_update",
      label: "Before update v0.1.1",
      size: 4096,
      eligibility: "older",
      vestadVersion: "0.1.1",
    })
  })

  it("reports a missing stamp as null rather than dropping the field", () => {
    const [point] = buildBackupTimeline([BASE], "0.1.2")
    expect(point?.vestadVersion).toBeNull()
  })
})
