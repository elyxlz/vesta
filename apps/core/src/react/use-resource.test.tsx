// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import { useResource } from "./use-resource";
import type { ReactElement } from "react";

interface Deferred {
  resolve: (value: string) => void;
  reject: (reason: Error) => void;
}

// A loader the test settles by hand, one deferred per call, in order.
function loader(): { load: () => Promise<string>; calls: Deferred[] } {
  const calls: Deferred[] = [];
  const load = () =>
    new Promise<string>((resolve, reject) => {
      calls.push({ resolve, reject });
    });
  return { load, calls };
}

function Probe({
  agent,
  load,
  retryMs,
  onRender = () => undefined,
}: {
  agent: string | null;
  load: () => Promise<string>;
  retryMs?: number;
  onRender?: () => void;
}): ReactElement {
  const resource = useResource(agent, load, { retryMs });
  onRender();
  return (
    <>
      <span data-testid="data">{resource.data ?? "none"}</span>
      <span data-testid="loading">
        {resource.loading ? "loading" : "settled"}
      </span>
      <span data-testid="error">
        {resource.error instanceof Error ? resource.error.message : "none"}
      </span>
      <button onClick={resource.reload}>reload</button>
      <button
        onClick={() => {
          resource.set("edited");
        }}
      >
        set
      </button>
    </>
  );
}

const text = (id: string): string => screen.getByTestId(id).textContent;

async function settle(
  deferred: Deferred | undefined,
  value: string,
): Promise<void> {
  if (deferred === undefined) throw new Error("no load in flight");
  await act(async () => {
    deferred.resolve(value);
    await Promise.resolve();
  });
}

async function fail(
  deferred: Deferred | undefined,
  message: string,
): Promise<void> {
  if (deferred === undefined) throw new Error("no load in flight");
  await act(async () => {
    deferred.reject(new Error(message));
    await Promise.resolve();
  });
}

describe("useResource", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("loads the value for the key and reports it", async () => {
    const { load, calls } = loader();
    render(<Probe agent="apollo" load={load} />);
    expect(text("loading")).toBe("loading");
    await settle(calls[0], "apollo-value");
    expect(text("data")).toBe("apollo-value");
    expect(text("loading")).toBe("settled");
  });

  it("loads nothing for a null key", () => {
    const { load, calls } = loader();
    render(<Probe agent={null} load={load} />);
    expect(calls).toHaveLength(0);
    expect(text("loading")).toBe("settled");
    expect(text("data")).toBe("none");
  });

  it("drops a result that lands for a previous key", async () => {
    const { load, calls } = loader();
    const view = render(<Probe agent="apollo" load={load} />);
    view.rerender(<Probe agent="hermes" load={load} />);
    expect(text("loading")).toBe("loading");
    await settle(calls[0], "apollo-value");
    expect(text("data")).toBe("none");
    expect(text("loading")).toBe("loading");
    await settle(calls[1], "hermes-value");
    expect(text("data")).toBe("hermes-value");
  });

  it("surfaces a failure and clears it on a reload that succeeds", async () => {
    const { load, calls } = loader();
    render(<Probe agent="apollo" load={load} />);
    await fail(calls[0], "offline");
    expect(text("error")).toBe("offline");
    expect(text("loading")).toBe("settled");
    act(() => {
      screen.getByText("reload").click();
    });
    expect(text("loading")).toBe("loading");
    expect(text("error")).toBe("none");
    await settle(calls[1], "apollo-value");
    expect(text("data")).toBe("apollo-value");
    expect(text("error")).toBe("none");
  });

  it("keeps the last data showing while a reload is in flight", async () => {
    const { load, calls } = loader();
    render(<Probe agent="apollo" load={load} />);
    await settle(calls[0], "first");
    act(() => {
      screen.getByText("reload").click();
    });
    expect(text("data")).toBe("first");
    expect(text("loading")).toBe("loading");
    await settle(calls[1], "second");
    expect(text("data")).toBe("second");
  });

  it("retries a failed load after the retry delay", async () => {
    vi.useFakeTimers();
    const { load, calls } = loader();
    render(<Probe agent="apollo" load={load} retryMs={1000} />);
    await fail(calls[0], "offline");
    expect(calls).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(calls).toHaveLength(2);
    await settle(calls[1], "apollo-value");
    expect(text("data")).toBe("apollo-value");
  });

  it("cancels a pending retry when the component unmounts", async () => {
    vi.useFakeTimers();
    const { load, calls } = loader();
    const view = render(<Probe agent="apollo" load={load} retryMs={1000} />);
    await fail(calls[0], "offline");
    view.unmount();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(calls).toHaveLength(1);
  });

  it("lets a write replace the loaded value without a refetch", async () => {
    const { load, calls } = loader();
    render(<Probe agent="apollo" load={load} />);
    await settle(calls[0], "loaded");
    act(() => {
      screen.getByText("set").click();
    });
    expect(text("data")).toBe("edited");
    expect(text("loading")).toBe("settled");
    expect(calls).toHaveLength(1);
  });

  it("calls the latest loader without restarting the load on re-render", async () => {
    const { load, calls } = loader();
    let renders = 0;
    const view = render(
      <Probe
        agent="apollo"
        load={load}
        onRender={() => {
          renders += 1;
        }}
      />,
    );
    view.rerender(
      <Probe
        agent="apollo"
        load={() => Promise.resolve("other")}
        onRender={() => {
          renders += 1;
        }}
      />,
    );
    expect(calls).toHaveLength(1);
    await settle(calls[0], "apollo-value");
    expect(text("data")).toBe("apollo-value");
    expect(renders).toBeGreaterThan(0);
  });
});
