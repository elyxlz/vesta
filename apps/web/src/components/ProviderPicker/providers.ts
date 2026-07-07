import type { FC } from "react";
import { ClaudeLogo, OpenRouterLogo } from "./logos";
import type { ProviderMode } from "./types";

// Brand art + UI copy that isn't in the manifest (logo, tagline). The provider's display NAME comes
// from the manifest (manifest.providers[id].display), so it isn't hardcoded here.
export interface ProviderMeta {
  id: ProviderMode;
  tagline: string;
  Logo: FC<{ className?: string }>;
}

export const PROVIDERS: ProviderMeta[] = [
  { id: "claude", tagline: "sign in with Claude (OAuth)", Logo: ClaudeLogo },
  {
    id: "openrouter",
    tagline: "pay per token via OpenRouter",
    Logo: OpenRouterLogo,
  },
];

export function providerMeta(id: ProviderMode): ProviderMeta {
  const meta = PROVIDERS.find((provider) => provider.id === id);
  if (!meta) throw new Error(`unknown provider: ${id}`);
  return meta;
}
