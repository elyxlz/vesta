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

  it("renders one row per service, sorted by name, with its exposure", () => {
    services = {
      whatsapp: { port: 9200, rev: 1, public: true },
      dashboard: { port: 9100, rev: 0, public: false },
    };
    render(<AgentServicesList />);

    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("dashboard");
    expect(rows[0]?.textContent).toContain("private");
    expect(rows[1]?.textContent).toContain("whatsapp");
    expect(rows[1]?.textContent).toContain("public");
  });

  it("shows an empty state when the agent has no services", () => {
    services = {};
    render(<AgentServicesList />);

    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByText(/no services yet/i)).toBeTruthy();
  });
});
