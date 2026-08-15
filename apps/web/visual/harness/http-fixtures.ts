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
  default_personality: "warm",
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
  },
  personalities: [
    {
      name: "warm",
      emoji: "🌞",
      title: "warm",
      description: "gentle, encouraging, always in your corner.",
      sample: "morning! ready when you are.",
      order: 1,
    },
    {
      name: "night-owl",
      emoji: "🌙",
      title: "night owl",
      description: "calm, dry, thinks best after midnight.",
      sample: "still up? me too. let's sort this.",
      order: 2,
    },
    {
      name: "spark",
      emoji: "⚡",
      title: "spark",
      description: "fast, playful, a little chaotic.",
      sample: "ooh, new plan. hear me out.",
      order: 3,
    },
    {
      name: "zen",
      emoji: "🌿",
      title: "zen",
      description: "unhurried, grounded, keeps things simple.",
      sample: "one thing at a time. what matters most?",
      order: 4,
    },
    {
      name: "captain",
      emoji: "🧭",
      title: "captain",
      description: "direct, organized, keeps you on course.",
      sample: "three things today. starting with the hardest.",
      order: 5,
    },
    {
      name: "wave",
      emoji: "🌊",
      title: "wave",
      description: "easygoing, warm, goes with your flow.",
      sample: "no rush. want me to take a look?",
      order: 6,
    },
  ],
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
