import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { AgentRow } from "@/lib/types";
import { CreatingStep } from "./index";

// A mutable roster the mocked useGateway reads: each test seeds the agent's
// buildPhase, then asserts the status line the component derives from it.
let roster: AgentRow[] = [];

vi.mock("@/providers/GatewayProvider", () => ({
  useGateway: () => ({ agents: roster }),
}));

function agentRow(name: string, buildPhase: AgentRow["buildPhase"]): AgentRow {
  return {
    name,
    status: "starting",
    activityState: "idle",
    buildPhase,
    startedAt: null,
    services: {},
  };
}

function renderCreating(agentName: string) {
  return render(
    <MemoryRouter>
      <CreatingStep
        agentName={agentName}
        done={false}
        error={null}
        onRetry={() => undefined}
      />
    </MemoryRouter>,
  );
}

describe("CreatingStep", () => {
  afterEach(() => {
    cleanup();
    roster = [];
  });

  it("shows the phase message for the creating agent's replica buildPhase", () => {
    roster = [agentRow("luna", "pulling")];
    renderCreating("luna");
    expect(screen.getByText("downloading the agent image...")).toBeTruthy();
  });

  it("follows the buildPhase as the roster advances", () => {
    roster = [agentRow("luna", "starting")];
    renderCreating("luna");
    expect(screen.getByText("starting up...")).toBeTruthy();
  });

  it("falls back to the neutral line when no roster entry has a phase yet", () => {
    roster = [];
    renderCreating("luna");
    expect(screen.getByText("setting things up...")).toBeTruthy();
  });
});
