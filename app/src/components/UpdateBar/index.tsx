import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { isTauri } from "@/lib/env";
import { checkAndInstallUpdate } from "@/api";

export function UpdateBar() {
  const [update, setUpdate] = useState<{
    version: string;
    installing: boolean;
  } | null>(null);
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
          className="overflow-hidden"
        >
          <div className="flex items-center justify-center gap-2 py-1.5 px-3 text-xs text-muted-foreground">
            <span>
              v{update!.version} {update!.installing ? "installed — restart to apply" : "available"}
            </span>
            <Button
              variant="link"
              size="sm"
              onClick={() => setDismissed(true)}
            >
              dismiss
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
