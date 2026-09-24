import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Markdown } from "@/lib/markdown";
import { CodeBlock } from ".";

afterEach(() => {
  cleanup();
});

describe("CodeBlock", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("labels the block with its language and colors keywords", () => {
    render(<CodeBlock code="def f(): pass" info="py" />);
    expect(screen.getByText("python")).toBeTruthy();
    expect(screen.getByText("def").style.color).toBe("var(--ansi-magenta)");
  });

  it("labels an unknown language as code", () => {
    render(<CodeBlock code="x" info={null} />);
    expect(screen.getByText("code")).toBeTruthy();
  });

  it("copies the raw code and shows Copied for 1.5 s", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CodeBlock code={"a\nb"} info="bash" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy" }));
      await Promise.resolve();
    });
    expect(writeText).toHaveBeenCalledWith("a\nb");
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
  });

  it("stays on Copy when the clipboard refuses", async () => {
    Object.assign(navigator, {
      clipboard: { writeText: () => Promise.reject(new Error("denied")) },
    });
    render(<CodeBlock code="x" info={null} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy" }));
      await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
  });
});

describe("Markdown code", () => {
  it("renders a fence with no language as a code block", () => {
    render(<Markdown>{"```\nplain fence\n```"}</Markdown>);
    expect(screen.getByText("code")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
  });

  it("keeps inline code inline", () => {
    render(<Markdown>{"run `ls` now"}</Markdown>);
    expect(screen.queryByRole("button", { name: "Copy" })).toBeNull();
    expect(screen.getByText("ls").tagName).toBe("CODE");
  });
});

describe("Markdown contrast in a user bubble", () => {
  it("tints inline code from the bubble's own text color", () => {
    render(<Markdown>{"run `ls` now"}</Markdown>);
    const chip = screen.getByText("ls");
    expect(chip.className).toContain("bg-current/10");
    expect(chip.className).not.toContain("bg-code");
  });

  it("draws links in the bubble text color inside a user bubble", () => {
    render(<Markdown>{"[docs](https://vesta.run)"}</Markdown>);
    expect(screen.getByText("docs").className).toContain(
      "group-data-[variant=default]/bubble:text-current",
    );
  });
});
