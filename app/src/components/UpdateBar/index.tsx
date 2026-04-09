import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { checkAndInstallUpdate, type UpdateInfo } from "@/api";
import { useTauri } from "@/providers/TauriProvider";
import { X, LoaderCircle } from "lucide-react";

export function UpdateBar() {
  const { isTauri } = useTauri();
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isTauri) return;
    checkAndInstallUpdate().then((u) => {
      if (u) setUpdate(u);
    });
  }, []);

  async function handleUpdate() {
    if (!update || installing) return;
    setInstalling(true);
    setError(null);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("install_update", { version: update.version });
      setDone(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setInstalling(false);
    }
  }

  const show = !!update && !dismissed;

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden flex justify-center py-2"
        >
          <div className="flex items-center gap-2 rounded-full border border-border bg-muted/50 py-1.5 pl-3.5 pr-1.5 text-sm">
            <span className="text-muted-foreground">
              {done
                ? `v${update!.version} installed — restart to apply`
                : update!.installed
                  ? `v${update!.version} installed — restart to apply`
                  : `v${update!.version} available`}
            </span>
            {error && <span className="text-destructive text-sm">{error}</span>}
            {!update!.installed && !done && (
              <button
                onClick={handleUpdate}
                disabled={installing}
                className="rounded-full bg-primary px-3.5 py-1 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {installing ? (
                  <LoaderCircle size={14} className="animate-spin" />
                ) : (
                  "Update"
                )}
              </button>
            )}
            <button
              onClick={() => setDismissed(true)}
              className="rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X size={14} />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
