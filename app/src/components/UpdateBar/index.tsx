import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { isTauri } from "@/lib/env";
import { checkAndInstallUpdate, runInstallScript } from "@/api";

export function UpdateBar() {
  const [update, setUpdate] = useState<{
    version: string;
    installing: boolean;
  } | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isTauri) return;
    checkAndInstallUpdate().then((u) => {
      if (u) setUpdate(u);
    });
  }, []);

  const handleInstall = useCallback(async () => {
    if (!update || busy) return;
    setBusy(true);
    try {
      await runInstallScript(update.version);
    } catch {
      // ignore
    } finally {
      setBusy(false);
    }
  }, [update, busy]);

  if (!update || dismissed) return null;

  return (
    <div className="flex items-center justify-center gap-2 py-1.5 px-3 text-xs text-muted-foreground animate-fade-slide-up">
      <span>
        v{update.version} {update.installing ? "installed — restart to apply" : "available —"}
      </span>
      {!update.installing && (
        <Button
          variant="link"
          size="xs"
          onClick={handleInstall}
          disabled={busy}
        >
          {busy ? "installing..." : "install"}
        </Button>
      )}
      <Button
        variant="link"
        size="xs"
        onClick={() => setDismissed(true)}
      >
        dismiss
      </Button>
    </div>
  );
}
