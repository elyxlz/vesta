import { useRef } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLayout } from "@/stores/use-layout";
import { useChatKeyboardFocus } from "./use-chat-keyboard-focus";

vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => true }));

const BASELINE_HEIGHT = 800;
const KEYBOARD_OPEN_HEIGHT = 500;

interface FakeVisualViewport {
  height: number;
  addEventListener: (type: string, listener: () => void) => void;
  removeEventListener: (type: string, listener: () => void) => void;
  resizeTo: (height: number) => void;
}

function installVisualViewport(height: number): FakeVisualViewport {
  const listeners = new Set<() => void>();
  const viewport: FakeVisualViewport = {
    height,
    addEventListener: (_type, listener) => listeners.add(listener),
    removeEventListener: (_type, listener) => listeners.delete(listener),
    resizeTo: (next) => {
      viewport.height = next;
      listeners.forEach((listener) => listener());
    },
  };
  Object.defineProperty(window, "visualViewport", {
    value: viewport,
    configurable: true,
  });
  return viewport;
}

function Harness() {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useChatKeyboardFocus(textareaRef);
  return <textarea ref={textareaRef} />;
}

let viewport: FakeVisualViewport;

beforeEach(() => {
  useLayout.setState({ chatKeyboardFocused: false });
  document.documentElement.style.height = "";
  viewport = installVisualViewport(BASELINE_HEIGHT);
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});

afterEach(cleanup);

function openKeyboard() {
  const view = render(<Harness />);
  screen.getByRole("textbox").focus();
  act(() => viewport.resizeTo(KEYBOARD_OPEN_HEIGHT));
  return view;
}

describe("useChatKeyboardFocus", () => {
  it("fits the app to the visual viewport when the keyboard opens over the composer", () => {
    openKeyboard();
    expect(useLayout.getState().chatKeyboardFocused).toBe(true);
    expect(document.documentElement.style.height).toBe(
      `${KEYBOARD_OPEN_HEIGHT}px`,
    );
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("tracks keyboard height changes while composing", () => {
    openKeyboard();
    act(() => viewport.resizeTo(KEYBOARD_OPEN_HEIGHT - 40));
    expect(document.documentElement.style.height).toBe(
      `${KEYBOARD_OPEN_HEIGHT - 40}px`,
    );
    expect(useLayout.getState().chatKeyboardFocused).toBe(true);
  });

  it("releases the app height when the keyboard closes", () => {
    openKeyboard();
    act(() => viewport.resizeTo(BASELINE_HEIGHT));
    expect(useLayout.getState().chatKeyboardFocused).toBe(false);
    expect(document.documentElement.style.height).toBe("");
  });

  it("releases the app height when the composer loses focus", () => {
    openKeyboard();
    screen.getByRole("textbox").blur();
    act(() => viewport.resizeTo(BASELINE_HEIGHT));
    expect(useLayout.getState().chatKeyboardFocused).toBe(false);
    expect(document.documentElement.style.height).toBe("");
  });

  it("releases the app height on unmount", () => {
    const view = openKeyboard();
    expect(document.documentElement.style.height).toBe(
      `${KEYBOARD_OPEN_HEIGHT}px`,
    );
    view.unmount();
    expect(document.documentElement.style.height).toBe("");
  });
});
