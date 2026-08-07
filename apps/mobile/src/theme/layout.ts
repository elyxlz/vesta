import { Platform } from "react-native";
import { designTokens } from "./generated";

export const radii = designTokens.radii;
export const spacing = designTokens.spacing;
export const navHeaderHeight = Platform.OS === "ios" ? 44 : 56;
