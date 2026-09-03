import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const loginItem = vi.hoisted(() => ({
  get: vi.fn<() => Promise<boolean>>(),
  set: vi.fn<(enabled: boolean) => Promise<void>>(),
}));
vi.mock("@/lib/native", () => ({ native: { loginItem } }));

import { useLoginItem } from "./use-login-item";

beforeEach(() => {
  loginItem.get.mockResolvedValue(false);
  loginItem.set.mockResolvedValue();
});
afterEach(cleanup);

describe("useLoginItem", () => {
  it("reports supported and reads the current state on mount", async () => {
    loginItem.get.mockResolvedValue(true);
    const { result } = renderHook(() => useLoginItem());
    expect(result.current.supported).toBe(true);
    await waitFor(() => {
      expect(result.current.enabled).toBe(true);
    });
  });

  it("writes the OS login item and reflects the new state when toggled", async () => {
    // Start enabled so the mount read is observable; wait for it before toggling off.
    loginItem.get.mockResolvedValue(true);
    const { result } = renderHook(() => useLoginItem());
    await waitFor(() => {
      expect(result.current.enabled).toBe(true);
    });
    await act(async () => {
      await result.current.setEnabled(false);
    });
    expect(loginItem.set).toHaveBeenCalledWith(false);
    expect(result.current.enabled).toBe(false);
  });
});
