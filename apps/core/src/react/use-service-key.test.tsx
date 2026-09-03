// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import { MINT_RETRY_DELAY_MS, useServiceKey } from "./use-service-key";
import type { ReactElement } from "react";
import type { ServiceKeyCache } from "../service-keys/service-keys";

function Probe({
  cache,
  agent,
  service = "dashboard",
  enabled = true,
  onRender = () => undefined,
}: {
  cache: ServiceKeyCache | null;
  agent: string;
  service?: string;
  enabled?: boolean;
  onRender?: () => void;
}): ReactElement {
  const { key, error } = useServiceKey(cache, agent, service, enabled);
  onRender();
  return (
    <>
      <span data-testid="key">{key ?? "none"}</span>
      <span data-testid="error">
        {error instanceof Error ? error.message : "none"}
      </span>
    </>
  );
}

function keyText(): string {
  return screen.getByTestId("key").textContent;
}

function errorText(): string {
  return screen.getByTestId("error").textContent;
}

// A cache whose mints are resolved by the test, so the window between requesting a pair and
// its key arriving is observable rather than a race.
function deferredCache(): {
  cache: ServiceKeyCache;
  requests: string[];
  settle: (agent: string, service: string, key: string) => void;
  fail: (agent: string, service: string, reason: Error) => void;
} {
  const pending = new Map<
    string,
    { resolve: (key: string) => void; reject: (reason: Error) => void }
  >();
  const requests: string[] = [];
  return {
    cache: {
      get: (agent, service) => {
        requests.push(`${agent}/${service}`);
        return new Promise<string>((resolve, reject) => {
          pending.set(`${agent}/${service}`, { resolve, reject });
        });
      },
    },
    requests,
    settle: (agent, service, key) => {
      const entry = pending.get(`${agent}/${service}`);
      if (!entry) throw new Error(`no pending mint for ${agent}/${service}`);
      entry.resolve(key);
    },
    fail: (agent, service, reason) => {
      const entry = pending.get(`${agent}/${service}`);
      if (!entry) throw new Error(`no pending mint for ${agent}/${service}`);
      entry.reject(reason);
    },
  };
}

// Let every already-settled mint promise land and React re-render from it. Two ticks,
// because a rejection travels through the hook's .then before its .catch sets the error.
async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

// Let the scheduled retry fire and its mint request land.
async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useServiceKey", () => {
  it("resolves the key for the requested agent", async () => {
    const { cache, settle } = deferredCache();
    render(<Probe cache={cache} agent="alpha" />);
    expect(keyText()).toBe("none");

    settle("alpha", "dashboard", "minted");
    await flush();
    expect(keyText()).toBe("minted");
  });

  it("mints nothing while disabled", async () => {
    const { cache, requests } = deferredCache();
    render(<Probe cache={cache} agent="alpha" enabled={false} />);
    await flush();

    expect(requests).toEqual([]);
    expect(keyText()).toBe("none");
  });

  it("mints nothing before a cache exists", async () => {
    render(<Probe cache={null} agent="alpha" />);
    await flush();
    expect(keyText()).toBe("none");
  });

  it("never reports a key minted for a previous agent", async () => {
    const { cache, requests, settle } = deferredCache();
    const { rerender } = render(<Probe cache={cache} agent="alpha" />);
    settle("alpha", "dashboard", "key-for-alpha");
    await flush();
    expect(keyText()).toBe("key-for-alpha");

    // beta's mint is still in flight: alpha's key must not be reported for beta.
    rerender(<Probe cache={cache} agent="beta" />);
    await flush();
    expect(keyText()).toBe("none");
    expect(requests).toEqual(["alpha/dashboard", "beta/dashboard"]);

    settle("beta", "dashboard", "key-for-beta");
    await flush();
    expect(keyText()).toBe("key-for-beta");
  });

  it("never reports a key minted for a previous service", async () => {
    const { cache, settle } = deferredCache();
    const { rerender } = render(
      <Probe cache={cache} agent="alpha" service="dashboard" />,
    );
    settle("alpha", "dashboard", "key-for-dashboard");
    await flush();
    expect(keyText()).toBe("key-for-dashboard");

    rerender(<Probe cache={cache} agent="alpha" service="voice" />);
    await flush();
    expect(keyText()).toBe("none");
  });

  it("drops a key that arrives after the requested agent changed", async () => {
    const { cache, settle } = deferredCache();
    const { rerender } = render(<Probe cache={cache} agent="alpha" />);
    rerender(<Probe cache={cache} agent="beta" />);

    // alpha's mint lands late, for a pair nobody is asking about any more.
    settle("alpha", "dashboard", "key-for-alpha");
    await flush();
    expect(keyText()).toBe("none");

    settle("beta", "dashboard", "key-for-beta");
    await flush();
    expect(keyText()).toBe("key-for-beta");
  });

  it("does not re-render for a mint that lands after the pair changed", async () => {
    const { cache, settle } = deferredCache();
    let renders = 0;
    const onRender = (): void => {
      renders += 1;
    };
    const { rerender } = render(
      <Probe cache={cache} agent="alpha" onRender={onRender} />,
    );
    rerender(<Probe cache={cache} agent="beta" onRender={onRender} />);
    const afterSwitch = renders;

    settle("alpha", "dashboard", "key-for-alpha");
    await flush();
    expect(renders).toBe(afterSwitch);
  });

  it("surfaces a mint failure instead of hanging", async () => {
    const { cache, fail } = deferredCache();
    render(<Probe cache={cache} agent="alpha" />);

    fail("alpha", "dashboard", new Error("mint refused"));
    await flush();
    expect(errorText()).toBe("mint refused");
    expect(keyText()).toBe("none");
  });

  // A gateway restart fails the mint, and nothing else would ever ask again: without the retry
  // the panel stays on its terminal error for the whole mount.
  it("retries a failed mint and clears the error once one succeeds", async () => {
    vi.useFakeTimers();
    const { cache, requests, fail, settle } = deferredCache();
    render(<Probe cache={cache} agent="alpha" />);

    fail("alpha", "dashboard", new Error("gateway restarting"));
    await flush();
    expect(errorText()).toBe("gateway restarting");
    expect(requests).toHaveLength(1);

    await advance(MINT_RETRY_DELAY_MS - 1);
    expect(requests).toHaveLength(1);

    await advance(1);
    expect(requests).toEqual(["alpha/dashboard", "alpha/dashboard"]);

    settle("alpha", "dashboard", "minted-on-retry");
    await flush();
    expect(keyText()).toBe("minted-on-retry");
    expect(errorText()).toBe("none");
  });

  it("keeps retrying while the mint keeps failing", async () => {
    vi.useFakeTimers();
    const { cache, requests, fail } = deferredCache();
    render(<Probe cache={cache} agent="alpha" />);

    for (const attempt of [1, 2, 3]) {
      fail("alpha", "dashboard", new Error(`refused ${String(attempt)}`));
      await flush();
      await advance(MINT_RETRY_DELAY_MS);
    }
    expect(requests).toHaveLength(4);
    expect(errorText()).toBe("refused 3");
  });

  it("cancels a pending retry when the component unmounts", async () => {
    vi.useFakeTimers();
    const { cache, requests, fail } = deferredCache();
    const { unmount } = render(<Probe cache={cache} agent="alpha" />);

    fail("alpha", "dashboard", new Error("mint refused"));
    await flush();
    unmount();

    await advance(MINT_RETRY_DELAY_MS * 3);
    expect(requests).toHaveLength(1);
  });

  it("clears a previous failure when a new pair is requested", async () => {
    const { cache, fail, settle } = deferredCache();
    const { rerender } = render(<Probe cache={cache} agent="alpha" />);
    fail("alpha", "dashboard", new Error("mint refused"));
    await flush();
    expect(errorText()).toBe("mint refused");

    rerender(<Probe cache={cache} agent="beta" />);
    settle("beta", "dashboard", "key-for-beta");
    await flush();
    expect(errorText()).toBe("none");
    expect(keyText()).toBe("key-for-beta");
  });
});
