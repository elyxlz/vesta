import Stack from "expo-router/stack";
import { headerTitleStyle } from "@/theme/sheets";

// Stack.Title replaces the layout's headerTitleStyle with its own, so a bare one loses the serif;
// every sheet titles itself through this instead.
export function SheetTitle({ children }: { children: string }) {
  return <Stack.Title style={headerTitleStyle}>{children}</Stack.Title>;
}
