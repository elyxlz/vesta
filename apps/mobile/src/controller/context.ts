import { createContext } from "react";
import type { Controller } from "@vesta/core";

// A single controller serves the whole connection. The context is null before connect and
// while the app is backgrounded (no live controller); connect screens never read it.
export const ControllerContext = createContext<Controller | null>(null);
