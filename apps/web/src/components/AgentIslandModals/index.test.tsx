import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentIslandModals } from "./index";

const handleBackup = vi.fn();

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob" }),
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
    setBackupDialogOpen: vi.fn(),
    handleBackup,
  }),
}));

describe("AgentIslandModals backup confirm", () => {
  afterEach(cleanup);

  it("runs the backup only after the user confirms", async () => {
    render(<AgentIslandModals />);
    expect(await screen.findByText("back up bob?")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "back up" }));
    expect(handleBackup).toHaveBeenCalledOnce();
  });
});
