import { Outlet } from "react-router-dom";
import { Titlebar } from "@/components/Titlebar";
import { isTauri } from "@/lib/env";
import { cn } from "@/lib/utils";

export function RootLayout() {
  return (
    <div className={cn("h-full bg-background flex flex-col", isTauri ? "pt-2" : "pt-3 sm:pt-4")}>
      <Titlebar />
      <div className="flex flex-col flex-1 min-h-0">
        <Outlet />
      </div>
    </div>
  );
}
