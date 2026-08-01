import type { ReactNode } from "react";
import { ControllerContext } from "../../src/controller/context";

export function ControllerProvider({ children }: { children: ReactNode }) {
  return (
    <ControllerContext.Provider value={null}>
      {children}
    </ControllerContext.Provider>
  );
}
