import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import * as agentsApi from "@/api/agents";
import type { ProviderInfo } from "@/api/agents";
import { fetchAgentClaudeModels } from "@/api/providers/claude";
import { ProviderCard } from "./index";

vi.mock("@/api/providers/claude", () => ({
  fetchAgentClaudeModels: vi.fn(),
}));

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "apollo", agent: { status: "idle" } }),
}));

vi.mock("@/providers/ModalsProvider", () => ({
  useModals: () => ({ handleOpenAuth: vi.fn() }),
}));

vi.mock("@/hooks/use-manifest", () => ({
  useManifest: () => undefined,
}));

vi.mock("./use-usage", () => ({
  useUsage: () => ({
    usage: null,
    loading: false,
    error: false,
    refresh: vi.fn(),
  }),
}));

const claudeProviderInfo: ProviderInfo = {
  kind: "claude",
  model: "sonnet",
  resolved_model: null,
  max_context_tokens: null,
  authed: true,
  plan: null,
};

describe("ProviderCard claude model switcher", () => {
  beforeEach(() => {
    vi.spyOn(agentsApi, "getProvider").mockResolvedValue(claudeProviderInfo);
    vi.mocked(fetchAgentClaudeModels).mockResolvedValue([
      { slug: "claude-opus-5", label: "Claude Opus 5", author: "Anthropic" },
    ]);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows a live slug from the agent endpoint once expanded", async () => {
    render(<ProviderCard />);
    await screen.findByText("sonnet");

    fireEvent.click(screen.getByRole("button", { name: /change model/i }));
    fireEvent.click(
      await screen.findByRole("button", { name: /more models/i }),
    );

    expect(await screen.findByText("Claude Opus 5")).toBeTruthy();
    expect(fetchAgentClaudeModels).toHaveBeenCalledWith("apollo");
  });

  it("submits the model change with the alias slug when Sonnet is picked", async () => {
    const setModelSpy = vi
      .spyOn(agentsApi, "setModel")
      .mockResolvedValue(undefined);
    render(<ProviderCard />);
    await screen.findByText("sonnet");

    fireEvent.click(screen.getByRole("button", { name: /change model/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^Sonnet$/ }));
    fireEvent.click(screen.getByRole("button", { name: /switch model/i }));

    await waitFor(() =>
      expect(setModelSpy).toHaveBeenCalledWith("apollo", "sonnet-latest"),
    );
  });

  it("degrades to the aliases alone when the live fetch fails", async () => {
    vi.mocked(fetchAgentClaudeModels).mockRejectedValue(new Error("boom"));
    render(<ProviderCard />);
    await screen.findByText("sonnet");

    fireEvent.click(screen.getByRole("button", { name: /change model/i }));
    expect(await screen.findByRole("button", { name: /^Opus$/ })).toBeTruthy();
    expect(
      await screen.findByRole("button", { name: /^Sonnet$/ }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /more models/i }));
    expect(await screen.findByText("no matches")).toBeTruthy();
  });
});
