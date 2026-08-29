import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BackupInfo } from "@/api";
import { BackupsDialog } from "./index";

const backup = vi.fn();
const restore = vi.fn();
const removeBackup = vi.fn();
const refreshBackups = vi.fn(() => Promise.resolve());
const onOpenChange = vi.fn();

// What the mocked providers report; each test sets what it needs before rendering.
const selected = {
  backups: [] as BackupInfo[],
  backupsFailed: false,
  isBusy: false,
};
const gateway = { gatewayVersion: "0.2.0" };

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({
    name: "bob",
    backups: selected.backups,
    backupsFailed: selected.backupsFailed,
    isBusy: selected.isBusy,
    operation: "idle",
    backup,
    refreshBackups,
    restore,
    removeBackup,
  }),
}));

vi.mock("@/providers/GatewayProvider", () => ({
  useGateway: () => ({ gatewayVersion: gateway.gatewayVersion }),
}));

const NIGHTLY: BackupInfo = {
  id: "nightly-id",
  agent_name: "bob",
  backup_type: "periodic",
  created_at: "20260529-040001",
  size: 2_470_000_000,
  vestad_version: "0.2.0",
};

const OLDER_MANUAL: BackupInfo = {
  id: "manual-id",
  agent_name: "bob",
  backup_type: "manual",
  created_at: "20260528-101500",
  size: 1024 * 1024,
  vestad_version: "0.1.9",
};

const NEWER_PRE_UPDATE: BackupInfo = {
  id: "pre-update-id",
  agent_name: "bob",
  backup_type: "pre_update",
  created_at: "20260527-090000",
  size: 512,
  from_version: "v0.2.0",
  vestad_version: "0.9.0",
};

function renderDialog() {
  render(<BackupsDialog open onOpenChange={onOpenChange} />);
}

function pointAt(index: number): HTMLElement {
  const point = screen.getAllByRole("listitem")[index];
  if (point === undefined) {
    throw new Error(`no timeline point at index ${String(index)}`);
  }
  return point;
}

function resetProviders() {
  vi.clearAllMocks();
  selected.backups = [OLDER_MANUAL, NEWER_PRE_UPDATE, NIGHTLY];
  selected.backupsFailed = false;
  selected.isBusy = false;
  gateway.gatewayVersion = "0.2.0";
}

describe("BackupsDialog timeline", () => {
  beforeEach(resetProviders);
  afterEach(cleanup);

  it("lists every snapshot newest first, labeled and sized", () => {
    renderDialog();
    const labels = screen
      .getAllByRole("listitem")
      .map((point) => point.textContent);
    expect(labels.length).toBe(3);
    expect(labels[0]).toContain("Automatic");
    expect(labels[1]).toContain("Manual");
    expect(labels[2]).toContain("Before update v0.2.0");
    expect(pointAt(0).textContent).toContain("2.3 GB");
  });

  it("shows each moment as a date and a time, never the raw stamp", () => {
    renderDialog();
    expect(screen.queryByText("20260529-040001")).toBeNull();
    expect(within(pointAt(0)).getByText(/2026/)).toBeTruthy();
  });

  it("re-reads the list whenever it opens", () => {
    renderDialog();
    expect(refreshBackups).toHaveBeenCalledOnce();
  });

  it("refuses a snapshot a newer vestad wrote, and says why", () => {
    renderDialog();
    const refused = within(pointAt(2));
    expect(
      refused.getByRole("button", { name: "restore" }).hasAttribute("disabled"),
    ).toBe(true);
    expect(refused.getByText(/made by a newer vestad/)).toBeTruthy();
    expect(
      refused
        .getByRole("button", { name: "delete snapshot" })
        .hasAttribute("disabled"),
    ).toBe(false);
  });

  it("disables every action while the agent is already working", () => {
    selected.isBusy = true;
    renderDialog();
    const actions = [
      ...screen.getAllByRole("button", { name: "restore" }),
      ...screen.getAllByRole("button", { name: "delete snapshot" }),
      screen.getByRole("button", { name: "back up" }),
    ];
    expect(actions.length).toBe(7);
    for (const action of actions) {
      expect(action.hasAttribute("disabled")).toBe(true);
    }
  });

  it("starts a new snapshot without leaving the timeline", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: "back up" }));
    expect(backup).toHaveBeenCalledOnce();
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});

describe("BackupsDialog confirm step", () => {
  beforeEach(resetProviders);
  afterEach(cleanup);

  const openRestoreConfirm = async (index: number) => {
    renderDialog();
    await userEvent.click(
      within(pointAt(index)).getByRole("button", { name: "restore" }),
    );
  };

  it("names the safety snapshot and the restart", async () => {
    await openRestoreConfirm(0);
    expect(screen.getByText(/safety snapshot first/)).toBeTruthy();
    expect(screen.getByText(/restarts them/)).toBeTruthy();
  });

  it("leaves the version line out when the snapshot matches the gateway", async () => {
    await openRestoreConfirm(0);
    expect(screen.queryByText(/converge the difference/)).toBeNull();
  });

  it("warns with both versions when the snapshot is older", async () => {
    await openRestoreConfirm(1);
    const warning = screen.getByText(/converge the difference/);
    expect(warning.textContent).toContain("0.1.9");
    expect(warning.textContent).toContain("0.2.0");
  });

  it("restores the chosen point and closes only once confirmed", async () => {
    await openRestoreConfirm(1);
    expect(restore).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "restore" }));
    expect(restore).toHaveBeenCalledWith("manual-id");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("drops a confirm the user cancels", async () => {
    await openRestoreConfirm(1);
    await userEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(restore).not.toHaveBeenCalled();
    expect(screen.getAllByRole("listitem").length).toBe(3);
  });

  it("deletes the chosen point only once confirmed, and stays open", async () => {
    renderDialog();
    await userEvent.click(
      within(pointAt(0)).getByRole("button", { name: "delete snapshot" }),
    );
    expect(screen.getByText(/can't be undone/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "delete" }));
    expect(removeBackup).toHaveBeenCalledWith("nightly-id");
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});

describe("BackupsDialog with no snapshots", () => {
  beforeEach(() => {
    resetProviders();
    selected.backups = [];
  });
  afterEach(cleanup);

  it("says so instead of showing an empty timeline", () => {
    renderDialog();
    expect(screen.getByText("no snapshots yet.")).toBeTruthy();
    expect(screen.queryAllByRole("listitem").length).toBe(0);
  });

  it("says the read failed rather than claiming the agent has no history", () => {
    selected.backupsFailed = true;
    renderDialog();
    expect(screen.getByText("couldn't load snapshots.")).toBeTruthy();
    expect(screen.queryByText("no snapshots yet.")).toBeNull();
  });
});

describe("BackupsDialog when a refresh fails over a loaded list", () => {
  beforeEach(() => {
    resetProviders();
    selected.backupsFailed = true;
  });
  afterEach(cleanup);

  it("keeps showing the snapshots it already has", () => {
    renderDialog();
    expect(screen.getAllByRole("listitem").length).toBe(3);
    expect(screen.queryByText("couldn't load snapshots.")).toBeNull();
  });
});
