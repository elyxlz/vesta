/// Format a token count compactly: 1M / 1.5M / 500K / 200K / 512.
/// Shared by the model picker (OpenRouter context_length) and the provider card
/// (context window) so the two render identically.
export function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  }
  if (n >= 1_000) return `${String(Math.round(n / 1_000))}K`;
  return String(n);
}
