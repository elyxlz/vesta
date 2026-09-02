import { useCallback, useState } from "react";
import { useResource } from "@vesta/core/react";
import { native } from "@/lib/native";
import type { AppUpdateStatus } from "@/lib/native/types";

type AppUpdatePhase = "idle" | "checking" | "downloading" | "ready" | "error";

export interface AppUpdate {
  /** True only in the desktop app; the browser cannot self-update. */
  supported: boolean;
  status: AppUpdateStatus;
  phase: AppUpdatePhase;
  /** Download progress, 0-100, meaningful while phase is "downloading". */
  percent: number;
  check: () => Promise<void>;
  /** Download the update; phase becomes "ready" when it can be applied. */
  start: () => Promise<void>;
  /** Quit and relaunch into the downloaded update. */
  relaunch: () => Promise<void>;
}

const IDLE_STATUS: AppUpdateStatus = { available: false, version: null };

type TransferPhase = "idle" | "downloading" | "ready" | "error";

/**
 * Drives the manual desktop self-update (App Settings Updates card, AppBehindScreen). Checks once
 * on mount so a caller only has to render; the browser build reports supported=false and no-ops.
 */
export function useAppUpdate(): AppUpdate {
  const updater = native.appUpdate;
  // The check is a resource keyed on the updater's presence: loading is the "checking" phase and
  // a rejected check is the error phase, until a transfer starts.
  const checked = useResource(updater ? "app-update" : null, () =>
    updater ? updater.check() : Promise.resolve(IDLE_STATUS),
  );
  const [transfer, setTransfer] = useState<{
    phase: TransferPhase;
    percent: number;
  }>({ phase: "idle", percent: 0 });

  const phase: AppUpdatePhase = checked.loading
    ? "checking"
    : checked.error !== null && transfer.phase === "idle"
      ? "error"
      : transfer.phase;

  const recheck = checked.reload;
  const check = useCallback(async () => {
    if (!updater) return;
    setTransfer({ phase: "idle", percent: 0 });
    recheck();
    await Promise.resolve();
  }, [updater, recheck]);

  const start = useCallback(async () => {
    if (!updater) return;
    setTransfer({ phase: "downloading", percent: 0 });
    try {
      await updater.download((percent) => {
        setTransfer({ phase: "downloading", percent });
      });
      setTransfer({ phase: "ready", percent: 100 });
    } catch {
      setTransfer({ phase: "error", percent: 0 });
    }
  }, [updater]);

  const relaunch = useCallback(async () => {
    if (!updater) return;
    try {
      await updater.install();
    } catch {
      setTransfer({ phase: "error", percent: 0 });
    }
  }, [updater]);

  return {
    supported: updater !== null,
    status: checked.data ?? IDLE_STATUS,
    phase,
    percent: transfer.percent,
    check,
    start,
    relaunch,
  };
}
