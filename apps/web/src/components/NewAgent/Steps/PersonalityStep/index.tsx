import { useState } from "react";
import { Button } from "@/components/ui/button";
import { FieldDescription } from "@/components/ui/field";

// Keep in sync with agent/core/skills/personality/presets/*.md.
// The list is intentionally static so onboarding works before the agent is reachable.
const PERSONALITIES = [
  {
    name: "dry",
    emoji: "😏",
    title: "dry",
    description: "lowercase, minimal, dry humor. the safe default.",
  },
  {
    name: "classic",
    emoji: "😂",
    title: "classic",
    description: "capital letters, full punctuation, 😂 reactions.",
  },
  {
    name: "polished",
    emoji: "🎩",
    title: "polished",
    description: "sentence case, precise. an aide, not a friend.",
  },
  {
    name: "terse",
    emoji: "⚪",
    title: "terse",
    description: "ultra-minimal. no humor, no emoji, pure utility.",
  },
  {
    name: "chill",
    emoji: "🤙",
    title: "chill",
    description: "lowercase, slangy, relaxed. bet, fr, ahahah.",
  },
  {
    name: "hype",
    emoji: "💅",
    title: "hype",
    description: "lowercase + CAPS, stretched words, emoji-rich.",
  },
] as const;

export function PersonalityStep({
  onPicked,
}: {
  onPicked: (name: string) => void;
}) {
  const [selected, setSelected] = useState<string>("dry");

  return (
    <div className="flex flex-col items-center gap-4 w-[560px] max-w-full px-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">pick a vibe</h2>
        <FieldDescription>
          starting point, not a commitment. ask your agent to change it anytime,
          and it'll keep shifting as it gets to know you.
        </FieldDescription>
      </div>

      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {PERSONALITIES.map((p) => {
          const isSelected = selected === p.name;
          return (
            <button
              key={p.name}
              onClick={() => setSelected(p.name)}
              className={`group flex h-full flex-col items-center gap-2 rounded-2xl border p-4 text-center transition-all cursor-pointer ${
                isSelected
                  ? "border-primary/60 bg-primary/5 ring-2 ring-primary/30"
                  : "border-border bg-input/30 hover:bg-input/60 hover:border-border/80"
              }`}
            >
              <span className="text-3xl leading-none" aria-hidden>
                {p.emoji}
              </span>
              <span className="text-sm font-semibold">{p.title}</span>
              <span className="text-[11px] leading-snug text-muted-foreground">
                {p.description}
              </span>
            </button>
          );
        })}
      </div>

      <Button className="w-full" onClick={() => onPicked(selected)}>
        continue
      </Button>
    </div>
  );
}
