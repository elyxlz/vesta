import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { AgentIslandModals } from "./index";

const setBackupDialogOpen = vi.fn();

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({
    name: "bob",
    backups: [],
    isBusy: false,
    backup: vi.fn(),
    refreshBackups: vi.fn(() => Promise.resolve()),
    restore: vi.fn(),
    removeBackup: vi.fn(),
  }),
}));

vi.mock("@/providers/GatewayProvider", () => ({
  useGateway: () => ({ gatewayVersion: "0.2.0" }),
}));

vi.mock("@/providers/ModalsProvider", () => ({
  useModals: () => ({
    showAuth: false,
    handleOpenAuth: vi.fn(),
    clearAuthState: vi.fn(),
    deleteDialogOpen: false,
    setDeleteDialogOpen: vi.fn(),
    handleDelete: vi.fn(),
    backupDialogOpen: true,
    setBackupDialogOpen,
  }),
}));

describe("AgentIslandModals", () => {
  afterEach(cleanup);

  it("opens the backups timeline for the selected agent", async () => {
    render(<AgentIslandModals />);
    expect(await screen.findByText("backups for bob")).toBeTruthy();
    expect(screen.getByRole("button", { name: "back up now" })).toBeTruthy();
  });
});
