import type { ComponentType } from "react";

export interface WidgetEntry {
  id: string;
  title: string;
  width?: number;
  height?: number;
  component: ComponentType;
}

export const widgets: WidgetEntry[] = [];
