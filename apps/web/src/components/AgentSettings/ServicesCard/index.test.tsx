import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ServicesCard } from "./index";

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob", agent: { services: {} } }),
}));

describe("ServicesCard", () => {
  afterEach(cleanup);

  it("explains the services in plain words below the card, naming the agent", () => {
    render(<ServicesCard />);
    expect(screen.getByText(/ask bob/i)).toBeTruthy();
  });
});
