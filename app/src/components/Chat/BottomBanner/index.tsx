import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";
import { AnimatedEllipsis } from "@/components/AnimatedEllipsis";

type BannerState = "new-message" | "reconnecting" | "error" | null;

function resolveBanner({
  hasNewMessage,
  wasConnected,
  connected,
  error,
}: BottomBannerProps): BannerState {
  if (wasConnected && !connected) return "reconnecting";
  if (error) return "error";
  if (hasNewMessage) return "new-message";
  return null;
}

const bannerConfig: Record<
  Exclude<BannerState, null>,
  { className: string; clickable?: boolean }
> = {
  "new-message": {
    className: "border-foreground bg-foreground text-background",
    clickable: true,
  },
  reconnecting: { className: "border-warning bg-warning text-white" },
  error: { className: "border-destructive bg-destructive text-white" },
};

interface BottomBannerProps {
  hasNewMessage: boolean;
  onScrollToBottom: () => void;
  wasConnected: boolean;
  connected: boolean;
  error: string | null;
}

export function BottomBanner(props: BottomBannerProps) {
  const active = resolveBanner(props);

  const content: Record<Exclude<BannerState, null>, React.ReactNode> = {
    "new-message": "new message",
    reconnecting: (
      <>
        Reconnecting <AnimatedEllipsis />
      </>
    ),
    error: props.error,
  };

  const config = active ? bannerConfig[active] : null;
  const Tag = config?.clickable ? motion.button : motion.div;

  return (
    <AnimatePresence>
      {active && config && (
        <Tag
          key={active}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onClick={config.clickable ? props.onScrollToBottom : undefined}
          className={cn(
            "absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 z-10 rounded-full border px-3 py-0.5 text-xs shadow-sm",
            active === "error"
              ? "max-w-[100%] text-center"
              : "whitespace-nowrap",
            config.clickable && "cursor-pointer",
            config.className,
          )}
        >
          {content[active]}
        </Tag>
      )}
    </AnimatePresence>
  );
}
