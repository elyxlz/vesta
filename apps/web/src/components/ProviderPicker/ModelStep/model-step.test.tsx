import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ModelStep } from "./index";

describe("ModelStep claude two-tier", () => {
  afterEach(cleanup);

  it("submits an alias from a primary button", () => {
    const onSubmit = vi.fn();
    render(
      <ModelStep
        initialModel="opus-latest"
        onSubmit={onSubmit}
        claudeLiveModels={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Sonnet$/ }));
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(onSubmit).toHaveBeenCalledWith("sonnet-latest");
  });

  it("shows a specific slug once the live list expands", () => {
    render(
      <ModelStep
        initialModel="opus-latest"
        onSubmit={vi.fn()}
        claudeLiveModels={[
          {
            slug: "claude-opus-5",
            label: "Claude Opus 5",
            author: "Anthropic",
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /more models/i }));
    expect(screen.getByText("Claude Opus 5")).toBeTruthy();
  });
});
