import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import type { ServiceInfo } from "@vesta/core";
import { AgentServicesList } from "./index";

let services: Record<string, ServiceInfo> = {};

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({
    name: "bob",
    agent: { services },
  }),
}));

describe("AgentServicesList", () => {
  afterEach(cleanup);

  it("renders one row per service, sorted by name, with its port", () => {
    services = {
      whatsapp: { port: 9200, rev: 1 },
      dashboard: { port: 9100, rev: 0 },
    };
    render(<AgentServicesList />);

    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("dashboard");
    expect(rows[0]?.textContent).toContain("9100");
    expect(rows[1]?.textContent).toContain("whatsapp");
    expect(rows[1]?.textContent).toContain("9200");
  });

  it("shows an empty state when the agent has no services", () => {
    services = {};
    render(<AgentServicesList />);

    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByText(/no services yet/i)).toBeTruthy();
  });

  it("explains the list in plain words, naming the agent", () => {
    services = { dashboard: { port: 9100, rev: 0 } };
    render(<AgentServicesList />);

    expect(screen.getByText(/ask bob/i)).toBeTruthy();
  });
});
