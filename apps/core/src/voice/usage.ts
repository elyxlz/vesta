// What a voice provider reports about its account, in the same words on every client and for
// every provider.

import type { VoiceAmount, VoiceUsage } from "../api/voice";

// Shown in place of a number that is loading or that the provider does not give.
const NO_VALUE = "—";

function formatAmount({ amount, unit }: VoiceAmount): string {
  if (unit === "usd") return `$${amount.toFixed(2)}`;
  if (unit === "hours") return `${amount.toFixed(2)} h`;
  if (unit === "credits")
    return `${Math.round(amount).toLocaleString("en-US")} credits`;
  return `${amount.toFixed(2)} ${unit}`;
}

// What the account used this month and what it has left, each part only when the provider
// gives it.
export function voiceUsageSummary(
  usage: VoiceUsage | null | undefined,
): string {
  const used = usage?.used ?? null;
  const left = usage?.left ?? null;
  const parts = [
    used && `${formatAmount(used)} used`,
    left && `${formatAmount(left)} left`,
  ].filter((part) => part !== null);
  return parts.length > 0 ? parts.join(" · ") : NO_VALUE;
}
