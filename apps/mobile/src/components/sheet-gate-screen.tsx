import type { ReactNode } from "react";

// iOS presents the blocking gates as native form sheets over the
// BlockingSheetGateView backdrop, so the route renders the sheet alone.
export function SheetGateScreen({ children }: { children: ReactNode }) {
  return children;
}
