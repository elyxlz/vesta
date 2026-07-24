import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useGateway } from "@/providers/GatewayProvider";

// How long the "already on latest" confirmation lingers after a manual check.
const LATEST_NOTICE_MS = 3000;

export function CheckForUpdates() {
  const { reachable, updateAvailable, checkForUpdate } = useGateway();
  const [checking, setChecking] = useState(false);
  const [onLatest, setOnLatest] = useState(false);
  const latestNoticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (latestNoticeTimer.current) clearTimeout(latestNoticeTimer.current);
    },
    [],
  );

  if (!reachable) return null;
  // The adjacent StatusPill owns the update pill, so when an update is
  // available we render nothing here and let it surface there instead.
  if (updateAvailable) return null;

  const onCheckForUpdate = async () => {
    if (latestNoticeTimer.current) clearTimeout(latestNoticeTimer.current);
    setOnLatest(false);
    setChecking(true);
    try {
      await checkForUpdate();
      // If a newer version exists the gateway flips updateAvailable and this
      // component renders nothing (the StatusPill shows the pill), so the
      // notice only surfaces when we're already up to date.
      setOnLatest(true);
      latestNoticeTimer.current = setTimeout(
        () => setOnLatest(false),
        LATEST_NOTICE_MS,
      );
    } finally {
      setChecking(false);
    }
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="xs"
      onClick={() => {
        void onCheckForUpdate();
      }}
      disabled={checking}
      className="text-muted-foreground"
    >
      {!onLatest && (
        <RefreshCw
          data-icon="inline-start"
          className={`size-3.5 ${checking ? "animate-spin" : ""}`}
        />
      )}
      {checking
        ? "checking..."
        : onLatest
          ? "on the latest version"
          : "check for updates"}
    </Button>
  );
}
