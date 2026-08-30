import type { Page } from "@playwright/test";
import type { ProviderContextPolicy, ProviderCatalog } from "@vesta/core";

export const AGENT = "luna";
export const GATEWAY_ORIGIN = "http://vestad.local";

interface Personality {
  name: string;
  emoji: string;
  title: string;
  description: string;
  sample: string;
  order: number;
}

const CONTEXT: ProviderContextPolicy = {
  default: 131072,
  max: 131072,
  presets: [{ tokens: 131072, label: "128K", note: "the full window" }],
};

export const PROVIDER_CATALOG: ProviderCatalog = {
  default_provider: "claude",
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
      models: ["glm-5.2", "glm-5-turbo", "glm-4.7"],
      model_names: {
        "glm-5.2": "GLM 5.2",
        "glm-5-turbo": "GLM 5 Turbo",
        "glm-4.7": "GLM 4.7",
      },
      default_model: "glm-5.2",
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
      models: ["kimi-for-coding", "kimi-for-coding-highspeed", "k3"],
      model_names: {
        "kimi-for-coding": "Coding",
        "kimi-for-coding-highspeed": "Coding Highspeed",
        k3: "K3",
      },
      default_model: "kimi-for-coding",
      context: CONTEXT,
    },
    openai: {
      display: "ChatGPT",
      order: 5,
      auth_kind: "device_oauth",
      models: ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
      model_names: {
        "gpt-5.6-sol": "GPT 5.6 Sol",
        "gpt-5.6-terra": "GPT 5.6 Terra",
        "gpt-5.6-luna": "GPT 5.6 Luna",
      },
      default_model: "gpt-5.6-sol",
      context: CONTEXT,
    },
  },
};

export const PERSONALITY_CATALOG: {
  default: string;
  presets: Personality[];
} = {
  default: "dry",
  presets: [
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

// Small DTO duplicated from the src OpenRouter module.
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

export const OPENAI_OAUTH_START = {
  auth_url: "https://chatgpt.com/device?visual-fixture",
  user_code: "WDJB-MJHT",
  session_id: "visual-openai-session",
};

export const OAUTH_CREDENTIALS = {
  credentials: JSON.stringify({ claudeAiOauth: { subscriptionType: "max" } }),
};

export const CLAUDE_MODELS = [
  { slug: "claude-opus-5", label: "Claude Opus 5", author: "Anthropic" },
  { slug: "claude-sonnet-5", label: "Claude Sonnet 5", author: "Anthropic" },
  { slug: "claude-haiku-4-5", label: "Claude Haiku 4.5", author: "Anthropic" },
];

// One gateway answer: an exact pathname on the gateway origin (or a full
// https:// URL for an external host), optionally narrowed to a method and to
// query params that must be present. `hang` leaves the request pending, which
// is how a loading state is held for the shot. `body` is raw (an SSE stream);
// `json` is the common case.
export interface RouteFixture {
  path: string;
  method?: string;
  query?: Record<string, string>;
  status?: number;
  json?: unknown;
  jsonSequence?: readonly [unknown, ...unknown[]];
  body?: string;
  contentType?: string;
  hang?: boolean;
}

// The GET /provider shape the settings card reads (a subset of the wire type).
export interface ProviderInfoFixture {
  kind: "claude" | "openrouter" | "zai" | "kimi" | "openai";
  model: string | null;
  resolved_model: string | null;
  max_context_tokens: number | null;
  authed: boolean;
  plan: string | null;
}

export function providerRoute(
  provider: ProviderInfoFixture,
  catalog: ProviderCatalog = PROVIDER_CATALOG,
): RouteFixture {
  return {
    path: `/agents/${AGENT}/provider`,
    method: "GET",
    json: { ...provider, catalog },
  };
}

// The answers every scenario starts from: a hermetic catch-all for the gateway
// origin, the onboarding catalogs and OAuth handshakes, and an empty agent
// whose HTTP server is ready. A scenario's own routes are registered after these, and
// Playwright hands a request to the last matching handler, so they win.
const BASE_ROUTES: RouteFixture[] = [
  {
    path: `/agents/${AGENT}/provider`,
    method: "GET",
    json: { authed: false, catalog: PROVIDER_CATALOG },
  },
  {
    path: `/agents/${AGENT}/personalities`,
    json: PERSONALITY_CATALOG,
  },
  {
    path: `/agents/${AGENT}/providers/openrouter/models/top`,
    json: OPENROUTER_MODELS,
  },
  {
    path: `/agents/${AGENT}/providers/claude/oauth/start`,
    json: OAUTH_START,
  },
  {
    path: `/agents/${AGENT}/providers/openai/oauth/start`,
    json: OPENAI_OAUTH_START,
  },
  {
    path: `/agents/${AGENT}/providers/claude/oauth/complete`,
    json: OAUTH_CREDENTIALS,
  },
  {
    path: `/agents/${AGENT}/providers/openai/oauth/complete`,
    json: { credentials: "visual-openai-credentials" },
  },
  {
    path: `/agents/${AGENT}/providers/claude/models`,
    json: CLAUDE_MODELS,
  },
  {
    path: `/agents/${AGENT}/providers/openrouter/validate-key`,
    json: {},
  },
  {
    path: `/agents/${AGENT}`,
    method: "GET",
    json: { status: "unprovisioned", booting: false },
  },
];

function matches(fixture: RouteFixture): (url: URL) => boolean {
  const external = fixture.path.startsWith("https://");
  const target = external ? new URL(fixture.path) : null;
  return (url) => {
    if (target) {
      if (url.origin !== target.origin || url.pathname !== target.pathname) {
        return false;
      }
    } else if (url.origin !== GATEWAY_ORIGIN || url.pathname !== fixture.path) {
      return false;
    }
    if (!fixture.query) return true;
    return Object.entries(fixture.query).every(
      ([key, value]) => url.searchParams.get(key) === value,
    );
  };
}

async function installRoute(page: Page, fixture: RouteFixture): Promise<void> {
  let sequenceIndex = 0;
  await page.route(matches(fixture), (route) => {
    if (fixture.method && route.request().method() !== fixture.method) {
      return route.fallback();
    }
    if (fixture.hang) return;
    if (fixture.body !== undefined) {
      return route.fulfill({
        status: fixture.status ?? 200,
        contentType: fixture.contentType ?? "text/plain",
        body: fixture.body,
      });
    }
    const sequence = fixture.jsonSequence;
    const json =
      sequence === undefined
        ? (fixture.json ?? {})
        : sequence[Math.min(sequenceIndex++, sequence.length - 1)];
    return route.fulfill({
      status: fixture.status ?? 200,
      json,
    });
  });
}

export async function installGatewayMocks(
  page: Page,
  routes: RouteFixture[],
): Promise<void> {
  await page.route(`${GATEWAY_ORIGIN}/**`, (route) =>
    route.fulfill({ json: {} }),
  );
  for (const fixture of [...BASE_ROUTES, ...routes]) {
    await installRoute(page, fixture);
  }
}
