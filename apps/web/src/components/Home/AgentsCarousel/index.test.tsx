import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent, waitFor } from "@testing-library/react";
import type { AgentRow } from "@/lib/types";
import { AgentsCarousel } from "./index";
import { AGENT_CAROUSEL_ITEM_STRIDE } from "./constants";

vi.mock("@/components/AgentCard", () => ({
  AgentCard: ({ agent }: { agent: AgentRow }) => <div>{agent.name}</div>,
}));

const AGENTS = ["ada", "bob", "cy"].map(
  (name) => ({ name }) as unknown as AgentRow,
);

function activeDot(container: HTMLElement) {
  return [...container.querySelectorAll("button")].find(
    (dot) => dot.style.opacity === "1",
  );
}

describe("AgentsCarousel active dot", () => {
  afterEach(cleanup);

  it("starts on the initial card without a scroll", async () => {
    const { container } = render(
      <AgentsCarousel agents={AGENTS} initialIndex={2} />,
    );

    await waitFor(() => {
      expect(activeDot(container)?.getAttribute("aria-label")).toBe("page 3");
    });
  });

  it("follows the card the scroller settles on", async () => {
    const { container } = render(<AgentsCarousel agents={AGENTS} />);
    const scroller =
      container.querySelector<HTMLDivElement>(".overflow-x-auto");
    if (!scroller) throw new Error("scroller not rendered");

    scroller.scrollLeft = AGENT_CAROUSEL_ITEM_STRIDE;
    fireEvent.scroll(scroller);

    await waitFor(() => {
      expect(activeDot(container)?.getAttribute("aria-label")).toBe("page 2");
    });
  });
});
