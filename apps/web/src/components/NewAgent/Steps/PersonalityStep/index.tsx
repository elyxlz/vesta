import { useState } from "react";
import { Button } from "@/components/ui/button";
import { FieldDescription } from "@/components/ui/field";

// Keep in sync with agent/core/prompts/personalities/*.md.
// The list is intentionally static so onboarding works before the agent is reachable.
const PERSONALITIES = [
  {
    name: "default",
    emoji: "😏",
    title: "sardonic",
    description: "sardonic best friend, dry humor, sharp-tongued",
  },
  {
    name: "girl-bff",
    emoji: "💅",
    title: "bff",
    description:
      "warm, validating, gossipy best friend energy. hypes you up and calls you out with love",
  },
  {
    name: "boy-bff",
    emoji: "🤜",
    title: "bro",
    description: "ride-or-die bro, loyal, dry humor, gives you hell with love",
  },
] as const;

export function PersonalityStep({
  onPicked,
}: {
  onPicked: (name: string) => void;
}) {
  const [selected, setSelected] = useState<string>("default");

  return (
    <div className="flex flex-col items-center gap-4 w-[480px] max-w-full px-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">pick a vibe</h2>
        <FieldDescription>
          you can change this later in settings.
        </FieldDescription>
      </div>

      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-3">
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
