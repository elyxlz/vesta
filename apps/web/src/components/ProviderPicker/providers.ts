import type { FC } from "react";
import {
  ClaudeLogo,
  KimiLogo,
  OpenAILogo,
  OpenRouterLogo,
  ZaiLogo,
} from "./logos";
import type { ProviderMode } from "./types";

// Brand art and UI copy that are presentation. Provider display names come from the agent catalog.
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
  {
    id: "zai",
    tagline: "use your GLM Coding Plan",
    Logo: ZaiLogo,
  },
  {
    id: "kimi",
    tagline: "use your Kimi membership",
    Logo: KimiLogo,
  },
  {
    id: "openai",
    tagline: "sign in with your ChatGPT subscription",
    Logo: OpenAILogo,
  },
];

export function providerMeta(id: ProviderMode): ProviderMeta {
  const meta = PROVIDERS.find((provider) => provider.id === id);
  if (!meta) throw new Error(`unknown provider: ${id}`);
  return meta;
}
