import type { ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Button } from "@/components/ui/button";
import { FieldDescription } from "@/components/ui/field";
import { fade, floatTransition, textSwap } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { glassAction } from "../glass";
import type { ChromeAction, ChromeActionKind, ChromeHeading } from "../chrome";

// Persistent shell around the swapping step body: one mounted heading and one
// mounted layout-animated action button, so a step change morphs them in place
// instead of remounting them with the body.
export function Chrome({
  heading,
  action,
  error,
  bodyKey,
  widthClass,
  onAction,
  children,
}: {
  heading: ChromeHeading | null;
  action: ChromeAction | null;
  error: string | null;
  bodyKey: string;
  widthClass: string;
  onAction: (kind: ChromeActionKind) => void;
  children: ReactNode;
}) {
  const reduced = useReducedMotion() ?? false;
  const float = floatTransition(reduced);
  const headingSwap = reduced ? fade : textSwap;
  return (
    <div className="flex w-full flex-col items-center gap-6">
      <AnimatePresence mode="wait">
        {heading && (
          <motion.div
            key={heading.title}
            {...headingSwap}
            className={cn(
              "flex max-w-full flex-col items-center gap-1 px-4 text-center",
              widthClass,
            )}
          >
            <h2 className="font-heading text-lg font-medium tracking-tight">
              {heading.title}
            </h2>
            <FieldDescription className="text-center text-[13px]">
              {heading.description}
            </FieldDescription>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        <motion.div
          key={bodyKey}
          {...float}
          className={cn("flex max-w-full justify-center", widthClass)}
        >
          {children}
        </motion.div>
      </AnimatePresence>

      <AnimatePresence>
        {action && (
          <motion.div
            layout
            key="action"
            {...float}
            className={cn("max-w-full px-4", widthClass)}
          >
            <Button
              className={cn("h-12 w-full", glassAction)}
              disabled={action.disabled}
              onClick={() => {
                onAction(action.kind);
              }}
            >
              <AnimatePresence mode="wait" initial={false}>
                <motion.span key={action.label} {...fade}>
                  {action.label}
                </motion.span>
              </AnimatePresence>
            </Button>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {error && (
          <motion.p
            {...fade}
            role="status"
            aria-live="polite"
            className="max-w-[560px] px-4 text-center text-xs text-destructive"
          >
            {error}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}
