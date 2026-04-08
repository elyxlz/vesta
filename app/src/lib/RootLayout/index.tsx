import { Outlet } from "react-router-dom";

export function RootLayout() {
  return (
    <div className="h-full bg-background flex flex-col">
      <div className="flex flex-col flex-1 min-h-0">
        <Outlet />
      </div>
    </div>
  );
}
