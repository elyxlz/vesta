import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";
import { AnimatedEllipsis } from "@/components/AnimatedEllipsis";

type BannerState = "reconnecting" | "error" | null;

function resolveBanner({
  wasConnected,
  connected,
  error,
}: BottomBannerProps): BannerState {
  if (wasConnected && !connected) return "reconnecting";
  if (error) return "error";
  return null;
}

const bannerConfig: Record<
  Exclude<BannerState, null>,
  { className: string }
> = {
  reconnecting: { className: "border-warning bg-warning text-white" },
  error: { className: "border-destructive bg-destructive text-white" },
};

interface BottomBannerProps {
  wasConnected: boolean;
  connected: boolean;
  error: string | null;
}

export function BottomBanner(props: BottomBannerProps) {
  const active = resolveBanner(props);

  const content: Record<Exclude<BannerState, null>, React.ReactNode> = {
    reconnecting: (
      <>
        Reconnecting <AnimatedEllipsis />
      </>
    ),
    error: props.error,
  };

  const config = active ? bannerConfig[active] : null;

  return (
    <AnimatePresence>
      {active && config && (
        <motion.div
          key={active}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className={cn(
            "absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 z-10 rounded-full border px-3 py-2 -my-1.5 text-xs shadow-sm",
            active === "error"
              ? "max-w-[100%] text-center"
              : "whitespace-nowrap",
            config.className,
          )}
        >
          {content[active]}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
