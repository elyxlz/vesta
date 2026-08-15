import type { Page } from "@playwright/test";
import type {
  AgentStatus,
  ProviderContextPolicy,
  ProviderManifest,
} from "@vesta/core";

export const AGENT = "luna";

// Small DTO duplicated on this side of the seam (the src Manifest type lives in
// the app tsconfig project): GET /manifest is the provider catalog plus the
// personality presets.
interface Personality {
  name: string;
  emoji: string;
  title: string;
  description: string;
  sample: string;
  order: number;
}

type Manifest = ProviderManifest & { personalities: Personality[] };

const CONTEXT: ProviderContextPolicy = {
  default: 131072,
  max: 131072,
  presets: [{ tokens: 131072, label: "128K", note: "the full window" }],
};

export const MANIFEST: Manifest = {
  default_provider: "claude",
  default_personality: "dry",
  providers: {
    claude: {
      display: "Claude",
      order: 1,
      auth_kind: "claude_oauth",
      models: "live",
      default_model: null,
      context: CONTEXT,
    },
    zai: {
      display: "Z.AI",
      order: 2,
      auth_kind: "subscription_key",
      models: ["glm-4.7"],
      model_names: { "glm-4.7": "GLM 4.7" },
      default_model: "glm-4.7",
      context: CONTEXT,
    },
    openrouter: {
      display: "OpenRouter",
      order: 3,
      auth_kind: "api_key",
      models: "live",
      default_model: null,
      context: CONTEXT,
    },
    kimi: {
      display: "Kimi Code",
      order: 4,
      auth_kind: "subscription_key",
      models: ["kimi-k2"],
      model_names: { "kimi-k2": "Kimi K2" },
      default_model: "kimi-k2",
      context: CONTEXT,
    },
    openai: {
      display: "ChatGPT",
      order: 5,
      auth_kind: "device_oauth",
      models: ["gpt-5.2-codex"],
      model_names: { "gpt-5.2-codex": "GPT 5.2 Codex" },
      default_model: "gpt-5.2-codex",
      context: CONTEXT,
    },
  },
  personalities: [
    {
      name: "dry",
      emoji: "😏",
      title: "dry",
      description: "lowercase, minimal, dry humor. the safe default.",
      sample: "nah. why though",
      order: 1,
    },
    {
      name: "classic",
      emoji: "😂",
      title: "classic",
      description:
        "capital letters, full punctuation, 😂 reserved for genuinely funny moments.",
      sample: "Oh no, want me to help?",
      order: 2,
    },
    {
      name: "polished",
      emoji: "🎩",
      title: "polished",
      description: "sentence case, precise, no slang. an aide, not a friend.",
      sample: "Understood. Shall I draft a note?",
      order: 3,
    },
    {
      name: "terse",
      emoji: "⚪",
      title: "terse",
      description: "ultra-minimal. no humor, no emoji, pure utility.",
      sample: "who to",
      order: 4,
    },
    {
      name: "chill",
      emoji: "🤙",
      title: "chill",
      description: "lowercase, slangy, relaxed. casual and loyal.",
      sample: "bet, lemme handle it",
      order: 5,
    },
    {
      name: "extra",
      emoji: "💅",
      title: "extra",
      description:
        "lowercase with CAPS for emphasis, stretched words, emoji-rich. maximally expressive.",
      sample: "OMGGG GIRL 💅",
      order: 6,
    },
  ],
};

// Small DTO duplicated from the src OpenRouter module, like Manifest above.
interface OpenRouterModelOption {
  slug: string;
  label: string;
  author: string;
  context_length?: number;
  input_price?: number | null;
  output_price?: number | null;
}

export const OPENROUTER_MODELS: OpenRouterModelOption[] = [
  {
    slug: "anthropic/claude-sonnet-5",
    label: "Claude Sonnet 5",
    author: "Anthropic",
    context_length: 200000,
    input_price: 3,
    output_price: 15,
  },
  {
    slug: "openai/gpt-5.2",
    label: "GPT 5.2",
    author: "OpenAI",
    context_length: 200000,
    input_price: 2.5,
    output_price: 10,
  },
  {
    slug: "moonshotai/kimi-k2",
    label: "Kimi K2",
    author: "MoonshotAI",
    context_length: 131072,
    input_price: 0.6,
    output_price: 2.5,
  },
];

export const OAUTH_START = {
  auth_url: "https://claude.ai/oauth/authorize?visual-fixture",
  session_id: "visual-oauth-session",
};

export interface GatewayMockOptions {
  agentStatus: AgentStatus;
  createResponse: { status: number; body: { error: string } } | null;
}

// Later-registered routes win in Playwright, so the hermetic catch-all for the
// fake gateway origin goes first and the specific answers override it.
export async function installGatewayMocks(
  page: Page,
  opts: GatewayMockOptions,
): Promise<void> {
  await page.route("**://vestad.local/**", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.route("**/manifest", (route) => route.fulfill({ json: MANIFEST }));
  await page.route("**/providers/claude/oauth/start", (route) =>
    route.fulfill({ json: OAUTH_START }),
  );
  await page.route("**/providers/openrouter/validate-key", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.route("**/providers/openrouter/models/top", (route) =>
    route.fulfill({ json: OPENROUTER_MODELS }),
  );
  await page.route(`**/agents/${AGENT}`, (route) =>
    route.fulfill({ json: { status: opts.agentStatus } }),
  );
  await page.route("**/agents", (route) => {
    const failure = opts.createResponse;
    if (failure !== null) {
      return route.fulfill({ status: failure.status, json: failure.body });
    }
    return route.fulfill({ json: {} });
  });
}
