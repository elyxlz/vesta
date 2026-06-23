import { useEffect, useState } from "react";
import { claudeProvider } from "@/api";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";

// Shown immediately; refined from vestad's /providers/claude/models so a newly
// added model appears without a code change. claude-code resolves the aliases.
const CLAUDE_FALLBACK: OpenRouterModelOption[] = [
  { slug: "opus", label: "Claude Opus", author: "Anthropic" },
  { slug: "sonnet", label: "Claude Sonnet", author: "Anthropic" },
  { slug: "haiku", label: "Claude Haiku", author: "Anthropic" },
];

/// The Claude model list as model-card options for the provider card's model
/// switcher. Starts from the static fallback and refines it from vestad.
/// `enabled` gates the fetch so the OpenRouter path (or a non-Claude agent)
/// doesn't issue a request it would throw away.
export function useClaudeModels(enabled = true): OpenRouterModelOption[] {
  const [models, setModels] =
    useState<OpenRouterModelOption[]>(CLAUDE_FALLBACK);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    claudeProvider
      .fetchModels()
      .then((items) => {
        if (cancelled || items.length === 0) return;
        setModels(
          items.map((m) => ({
            slug: m.id,
            label: m.label,
            author: "Anthropic",
          })),
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return models;
}
