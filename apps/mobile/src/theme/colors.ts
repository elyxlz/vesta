import { designTokens } from "./generated";

export interface AppColors {
  background: string;
  elevated: string;
  card: string;
  text: string;
  secondaryText: string;
  tertiaryText: string;
  border: string;
  accent: string;
  accentText: string;
  accentSoft: string;
  interactive: string;
  success: string;
  warning: string;
  danger: string;
  input: string;
  code: string;
}

function appColors(theme: "light" | "dark"): AppColors {
  const colors = designTokens.colors[theme];
  return {
    background: colors.background,
    elevated: colors.popover,
    card: colors.card,
    text: colors.foreground,
    secondaryText: colors["muted-foreground"],
    tertiaryText: colors["tertiary-foreground"],
    border: colors.border,
    accent: colors.primary,
    accentText: colors["primary-foreground"],
    accentSoft: colors["primary-soft"],
    interactive: colors.interactive,
    success: colors.success,
    warning: colors.warning,
    danger: colors.destructive,
    input: colors.input,
    code: colors.code,
  };
}

export const darkColors: AppColors = appColors("dark");

export const lightColors: AppColors = appColors("light");
