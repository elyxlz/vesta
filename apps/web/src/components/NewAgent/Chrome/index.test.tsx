import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { Chrome } from "./index";

function renderChrome(overrides: Partial<Parameters<typeof Chrome>[0]> = {}) {
  return render(
    <Chrome
      heading={{ title: "new agent", description: "give them a name." }}
      action={{ kind: "submit-name", label: "continue", disabled: false }}
      bodyKey="name"
      widthClass="w-[320px]"
      actionWidthClass="w-[320px]"
      onAction={() => undefined}
      {...overrides}
    >
      <span>body content</span>
    </Chrome>,
  );
}

describe("Chrome", () => {
  afterEach(cleanup);

  it("renders the heading, the body, and the action label", () => {
    renderChrome();
    expect(screen.getByText("new agent")).toBeTruthy();
    expect(screen.getByText("body content")).toBeTruthy();
    expect(screen.getByRole("button", { name: "continue" })).toBeTruthy();
  });

  it("fires onAction with the action kind on click", () => {
    const onAction = vi.fn();
    renderChrome({ onAction });
    fireEvent.click(screen.getByRole("button", { name: "continue" }));
    expect(onAction).toHaveBeenCalledWith("submit-name");
  });

  it("disables the button when the action is disabled", () => {
    renderChrome({
      action: { kind: "submit-name", label: "continue", disabled: true },
    });
    expect(
      screen.getByRole("button", { name: "continue" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("hides the heading and the action when they are null", () => {
    renderChrome({ heading: null, action: null });
    expect(screen.queryByText("new agent")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
