import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ModelStep } from "./index";

const aliases = [
  { slug: "opus", label: "Opus", author: "Anthropic" },
  { slug: "sonnet", label: "Sonnet", author: "Anthropic" },
];

describe("ModelStep claude two-tier", () => {
  afterEach(cleanup);

  it("submits an alias from a primary button", () => {
    const onSubmit = vi.fn();
    render(
      <ModelStep
        initialModel="opus"
        onSubmit={onSubmit}
        claudeMode={{ aliases, liveModels: null }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Sonnet$/ }));
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(onSubmit).toHaveBeenCalledWith("sonnet");
  });

  it("shows a specific slug once the live list expands", () => {
    render(
      <ModelStep
        initialModel="opus"
        onSubmit={vi.fn()}
        claudeMode={{
          aliases,
          liveModels: [
            {
              slug: "claude-opus-5",
              label: "Claude Opus 5",
              author: "Anthropic",
            },
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /more models/i }));
    expect(screen.getByText("Claude Opus 5")).toBeTruthy();
  });
});
