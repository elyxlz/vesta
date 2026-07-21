import { createContext, use } from "react";
import type { Controller } from "@vesta/core";

// A single controller serves the whole connection. The context is null before connect and
// while the app is backgrounded (no live controller); connect screens never read it.
export const ControllerContext = createContext<Controller | null>(null);

export function useController(): Controller {
  const value = use(ControllerContext);
  if (!value) {
    throw new Error("useController must be used within ControllerProvider");
  }
  return value;
}
