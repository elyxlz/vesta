import { useCallback, useEffect, useState } from "react";
import { native } from "@/lib/native";
import type { AppUpdateStatus } from "@/lib/native/types";

export type AppUpdatePhase =
  "idle" | "checking" | "downloading" | "ready" | "error";

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

/**
 * Drives the manual desktop self-update (App Settings Updates card, AppBehindScreen). Checks once
 * on mount so a caller only has to render; the browser build reports supported=false and no-ops.
 */
export function useAppUpdate(): AppUpdate {
  const updater = native.appUpdate;
  const [status, setStatus] = useState<AppUpdateStatus>(IDLE_STATUS);
  const [phase, setPhase] = useState<AppUpdatePhase>("idle");
  const [percent, setPercent] = useState(0);

  const check = useCallback(async () => {
    if (!updater) return;
    setPhase("checking");
    try {
      setStatus(await updater.check());
      setPhase("idle");
    } catch {
      setPhase("error");
    }
  }, [updater]);

  const start = useCallback(async () => {
    if (!updater) return;
    setPercent(0);
    setPhase("downloading");
    try {
      await updater.download(setPercent);
      setPhase("ready");
    } catch {
      setPhase("error");
    }
  }, [updater]);

  const relaunch = useCallback(async () => {
    if (!updater) return;
    try {
      await updater.install();
    } catch {
      setPhase("error");
    }
  }, [updater]);

  useEffect(() => {
    void check();
  }, [check]);

  return {
    supported: updater !== null,
    status,
    phase,
    percent,
    check,
    start,
    relaunch,
  };
}
