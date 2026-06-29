import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

// Shared scroll surface for the settings pages: the page header / tab row stays
// fixed and only this container scrolls, with shadcn's scroll-aware `scroll-fade`
// softening whichever edge still has hidden content.
//
// The container itself spans the full width so its scrollbar sits flush with the
// inset-frame edge; the horizontal page padding lives on the inner wrapper instead,
// keeping content inset while the scrollbar reaches the edge.
export function SettingsScrollArea({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "scroll-fade min-h-0 flex-1 overflow-y-auto py-4 [scrollbar-gutter:stable]",
        className,
      )}
    >
      <div className="px-page">{children}</div>
    </div>
  );
}
