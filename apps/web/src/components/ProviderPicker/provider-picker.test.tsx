import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import type { Manifest } from "@/api/manifest";
import { fetchClaudeModels } from "@/api/providers/claude";
import { ProviderPicker } from "./index";

const CLAUDE_CREDS = JSON.stringify({
  claudeAiOauth: { subscriptionType: "max" },
});
const OPENAI_CREDS = JSON.stringify({ tokens: {} });

const LIVE_CLAUDE_MODEL = {
  slug: "claude-opus-5",
  label: "Claude Opus 5",
  author: "Anthropic",
};

vi.mock("@/api/providers/claude", () => ({
  startOAuth: vi.fn(() => new Promise(() => undefined)),
  fetchClaudeModels: vi.fn(() => Promise.resolve([LIVE_CLAUDE_MODEL])),
}));

vi.mock("./AuthStep", () => ({
  AuthStep: ({
    onCredentialsReady,
  }: {
    onCredentialsReady: (credentials: string) => void;
  }) => (
    <button
      type="button"
      onClick={() => {
        onCredentialsReady(CLAUDE_CREDS);
      }}
    >
      finish claude auth
    </button>
  ),
}));

vi.mock("./OpenAIAuthStep", () => ({
  OpenAIAuthStep: ({
    onCredentialsReady,
  }: {
    onCredentialsReady: (credentials: string) => void;
  }) => (
    <button
      type="button"
      onClick={() => {
        onCredentialsReady(OPENAI_CREDS);
      }}
    >
      finish openai auth
    </button>
  ),
}));

const manifest: Manifest = {
  default_provider: "claude",
  default_personality: "warm",
  personalities: [],
  providers: {
    claude: {
      display: "Claude",
      order: 0,
      auth_kind: "claude_oauth",
      models: "live",
      default_model: null,
      context: {
        default: 1_000_000,
        max: 1_000_000,
        defaults_by_plan: { max: 1_000_000, pro: 200_000, free: 200_000 },
        presets: [
          {
            tokens: 1_000_000,
            label: "1M",
            note: "most context",
            plans: ["max"],
          },
          { tokens: 500_000, label: "500K", note: "balanced", plans: ["max"] },
          { tokens: 200_000, label: "200K", note: "cheapest" },
        ],
      },
    },
    openai: {
      display: "ChatGPT",
      order: 1,
      auth_kind: "device_oauth",
      models: ["gpt-5.6-sol"],
      default_model: "gpt-5.6-sol",
      context: {
        default: 272_000,
        max: 272_000,
        presets: [{ tokens: 272_000, label: "272K", note: "full window" }],
      },
    },
  },
};

vi.mock("@/hooks/use-manifest", () => ({
  useManifest: () => manifest,
}));

describe("ProviderPicker defaults-only onboarding", () => {
  afterEach(cleanup);

  it("walks Claude through model and context steps and reports the picked window", async () => {
    const onDone = vi.fn();
    render(<ProviderPicker defaultsOnly onDone={onDone} />);

    fireEvent.click(screen.getByRole("button", { name: /Claude/ }));
    fireEvent.click(screen.getByRole("button", { name: /finish claude auth/ }));

    // A live catalog has no static default model, so auth must land on the model step.
    expect(onDone).not.toHaveBeenCalled();
    // Credentials being ready must trigger the live-catalog prefetch.
    expect(fetchClaudeModels).toHaveBeenCalled();

    // The two Claude alias buttons are always present on the model step.
    expect(screen.getByRole("button", { name: /^Opus$/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Sonnet$/ })).toBeTruthy();

    // Expanding "more models" reveals the prefetched live slug, once the fetch resolves.
    fireEvent.click(screen.getByRole("button", { name: /more models/i }));
    expect(await screen.findByText("Claude Opus 5")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    fireEvent.click(screen.getByRole("button", { name: /200K/ }));
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(onDone).toHaveBeenCalledWith({
      kind: "claude",
      credentials: CLAUDE_CREDS,
      model: "opus-latest",
      maxContextTokens: 200_000,
    });
  });

  it("still finishes a static-catalog provider with its defaults right after auth", () => {
    const onDone = vi.fn();
    render(<ProviderPicker defaultsOnly onDone={onDone} />);

    fireEvent.click(screen.getByRole("button", { name: /ChatGPT/ }));
    fireEvent.click(screen.getByRole("button", { name: /finish openai auth/ }));

    expect(onDone).toHaveBeenCalledWith({
      kind: "openai",
      credentials: OPENAI_CREDS,
      model: "gpt-5.6-sol",
      maxContextTokens: 272_000,
    });
  });
});
