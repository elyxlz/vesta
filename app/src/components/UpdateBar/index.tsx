import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { isTauri } from "@/lib/env";
import { checkAndInstallUpdate, type UpdateInfo } from "@/api";
import { openExternalUrl } from "@/lib/open-external-url";
import { X } from "lucide-react";

export function UpdateBar() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!isTauri) return;
    checkAndInstallUpdate().then((u) => {
      if (u) setUpdate(u);
    });
  }, []);

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
          <div className="flex items-center gap-2 rounded-full border border-border bg-muted/50 py-1 pl-3 pr-1 text-xs">
            <span className="text-muted-foreground">
              v{update!.version}{" "}
              {update!.installed ? "installed — restart to apply" : "available"}
            </span>
            {!update!.installed && update!.releaseUrl && (
              <button
                onClick={() => openExternalUrl(update!.releaseUrl!)}
                className="rounded-full bg-primary px-3 py-0.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                Update
              </button>
            )}
            <button
              onClick={() => setDismissed(true)}
              className="rounded-full p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X size={12} />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
