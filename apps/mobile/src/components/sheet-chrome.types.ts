import type { ReactNode } from "react";

export interface SheetChromeProps {
  title?: string;
  closeLabel?: string;
  grabber?: boolean;
  tintColor?: string;
  action?: {
    accessibilityLabel: string;
    onPress: () => void;
    icon: ReactNode;
  };
}
