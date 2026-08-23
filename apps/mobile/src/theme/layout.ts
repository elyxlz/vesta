import { designTokens } from "./generated";

export const radii = designTokens.radii;
export const spacing = designTokens.spacing;
export const navHeaderHeight = process.env.EXPO_OS === "ios" ? 44 : 56;
