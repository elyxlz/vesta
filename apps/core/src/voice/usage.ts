// What a voice provider reports about its account, in the same words on every client. A
// client adds only its own label.

import type { SttUsage, TtsUsage } from "../api/voice";

// Shown in place of a number that is loading or that the provider does not give.
const NO_VALUE = "—";

function formatBalance(balance: { amount?: number; units?: string }): string {
  const amount = balance.amount ?? 0;
  const units = (balance.units ?? "").toLowerCase();
  if (units === "usd") return `$${amount.toFixed(2)}`;
  if (units === "hour" || units === "hours") return `${amount.toFixed(2)} h`;
  return `${amount.toFixed(2)} ${balance.units ?? ""}`.trim();
}

// The hours used and the balance left, or the placeholder until the provider gives both.
export function sttUsageSummary(usage: SttUsage | null | undefined): string {
  const results = usage?.usage?.results;
  const balance = usage?.balance?.balances?.[0];
  if (!results || !balance) return NO_VALUE;
  const hours = results.reduce(
    (total, result) => total + (result.hours ?? 0),
    0,
  );
  return `${hours.toFixed(2)} h used · ${formatBalance(balance)} left`;
}

// A provider with a character quota reports the count, and one with none reports the balance
// of its account. `kind` says which one the value is.
export function ttsUsage(usage: TtsUsage | null | undefined): {
  kind: "characters" | "balance";
  value: string;
} {
  const balance = usage?.usage?.balances?.[0];
  if (balance) {
    return { kind: "balance", value: `${formatBalance(balance)} left` };
  }
  const count = usage?.usage?.character_count;
  const limit = usage?.usage?.character_limit;
  return {
    kind: "characters",
    value:
      typeof count === "number" && typeof limit === "number"
        ? `${count.toLocaleString("en-US")} / ${limit.toLocaleString("en-US")}`
        : NO_VALUE,
  };
}
