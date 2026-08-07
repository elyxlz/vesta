import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as api from "@/api/agents";
import { BackupsCard } from "./index";

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob" }),
}));

const settings = (enabled: boolean): api.AgentBackupSettings => ({
  enabled,
  retention: { periodic: 2, pre_update_versions: 2 },
  has_override: false,
});

describe("BackupsCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(cleanup);

  it("reflects the fetched enabled state", async () => {
    vi.spyOn(api, "fetchAgentBackupSettings").mockResolvedValue(settings(true));
    render(<BackupsCard />);
    const toggle = await screen.findByRole("switch");
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("PUTs the new value on toggle", async () => {
    vi.spyOn(api, "fetchAgentBackupSettings").mockResolvedValue(settings(true));
    const setSpy = vi
      .spyOn(api, "setAgentBackupSettings")
      .mockResolvedValue(settings(false));
    render(<BackupsCard />);
    const toggle = await screen.findByRole("switch");
    await userEvent.click(toggle);
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith("bob", false);
    });
  });
});
