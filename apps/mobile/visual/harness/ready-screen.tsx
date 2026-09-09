import type { ReactNode } from "react";
import { View } from "react-native";
import { useBootTransitionPhase } from "../../src/components/BootTransition";

// Keep the signal on the visible screen: native sheets hide the underlying
// navigator from accessibility, and compatibility gates replace it entirely.
export function ReadyScreen({ children }: { children: ReactNode }) {
  const { active } = useBootTransitionPhase();
  return (
    <>
      {children}
      {!active && (
        <View
          style={{ position: "absolute", top: "50%", left: "50%", width: 1, height: 1 }}
          pointerEvents="none"
          collapsable={false}
          testID="visual-harness-ready"
        />
      )}
    </>
  );
}
