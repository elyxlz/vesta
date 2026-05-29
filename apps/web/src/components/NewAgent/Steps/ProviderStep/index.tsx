import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import type { OpenRouterConfig } from "@/api/agents";

const DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4";

type Mode = "claude" | "openrouter";

export function ProviderStep({
  onChosen,
}: {
  onChosen: (openrouter: OpenRouterConfig | null) => void;
}) {
  const [mode, setMode] = useState<Mode>("claude");
  const [key, setKey] = useState("");
  const [model, setModel] = useState(DEFAULT_OPENROUTER_MODEL);
  const [zdr, setZdr] = useState(true);

  const canContinue =
    mode === "claude" || (key.trim() !== "" && model.trim() !== "");

  const submit = () => {
    if (!canContinue) return;
    onChosen(
      mode === "openrouter"
        ? { key: key.trim(), model: model.trim(), zdr }
        : null,
    );
  };

  const cardClass = (active: boolean) =>
    `flex flex-1 flex-col items-center gap-1 rounded-2xl border p-4 text-center transition-all cursor-pointer ${
      active
        ? "border-primary/60 bg-primary/5 ring-2 ring-primary/30"
        : "border-border bg-input/30 hover:bg-input/60 hover:border-border/80"
    }`;

  return (
    <div className="flex flex-col items-center gap-4 w-[360px] max-w-full px-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">how should it run?</h2>
        <FieldDescription>
          use your Claude account, or bring an OpenRouter API key.
        </FieldDescription>
      </div>

      <div className="flex w-full gap-2">
        <button
          className={cardClass(mode === "claude")}
          onClick={() => setMode("claude")}
        >
          <span className="text-sm font-semibold">Claude account</span>
          <span className="text-[11px] leading-snug text-muted-foreground">
            sign in with Claude (OAuth)
          </span>
        </button>
        <button
          className={cardClass(mode === "openrouter")}
          onClick={() => setMode("openrouter")}
        >
          <span className="text-sm font-semibold">OpenRouter key</span>
          <span className="text-[11px] leading-snug text-muted-foreground">
            pay per token via OpenRouter
          </span>
        </button>
      </div>

      {mode === "openrouter" && (
        <FieldGroup className="w-full gap-3">
          <Field>
            <FieldLabel htmlFor="or-key">API key</FieldLabel>
            <Input
              id="or-key"
              type="password"
              placeholder="sk-or-v1-..."
              value={key}
              onChange={(e) => setKey(e.target.value)}
              autoFocus
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="or-model">Model</FieldLabel>
            <Input
              id="or-model"
              placeholder={DEFAULT_OPENROUTER_MODEL}
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
            <FieldDescription>
              any OpenRouter slug. tool-heavy skills work best on anthropic/*
              models.
            </FieldDescription>
          </Field>
          <div className="flex w-full items-center justify-between gap-3">
            <div className="flex flex-col">
              <span className="text-xs font-medium">zero data retention</span>
              <span className="text-[11px] text-muted-foreground">
                only route to providers that don't store data
              </span>
            </div>
            <Switch checked={zdr} onCheckedChange={setZdr} />
          </div>
        </FieldGroup>
      )}

      <Button className="w-full" onClick={submit} disabled={!canContinue}>
        continue
      </Button>
    </div>
  );
}
