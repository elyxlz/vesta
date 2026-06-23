import type { FC } from "react";
import { ClaudeLogo, OpenRouterLogo } from "./logos";
import type { ProviderMode } from "./types";

// Single source of truth for which providers the picker offers and how they're
// branded. ChoiceStep renders its cards from this list and each step resolves
// its logo here, so adding a provider is one entry (+ its logo + flow wiring in
// ProviderPicker) rather than edits scattered across components.
export interface ProviderMeta {
  id: ProviderMode;
  label: string;
  tagline: string;
  Logo: FC<{ className?: string }>;
}

export const PROVIDERS: ProviderMeta[] = [
  {
    id: "claude",
    label: "Claude account",
    tagline: "sign in with Claude (OAuth)",
    Logo: ClaudeLogo,
  },
  {
    id: "openrouter",
    label: "OpenRouter key",
    tagline: "pay per token via OpenRouter",
    Logo: OpenRouterLogo,
  },
];

export function providerMeta(id: ProviderMode): ProviderMeta {
  const meta = PROVIDERS.find((provider) => provider.id === id);
  if (!meta) throw new Error(`unknown provider: ${id}`);
  return meta;
}
