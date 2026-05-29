import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import { openrouterProvider } from "@/api";

type OpenRouterModelOption = openrouterProvider.OpenRouterModelOption;
import { ProviderIcon } from "../ProviderIcon";
import { fuzzyMatch } from "../fuzzy";

export function ModelStep({
  initialModel,
  onModelChange,
  onSubmit,
}: {
  initialModel: string;
  onModelChange: (model: string) => void;
  onSubmit: (model: string) => void;
}) {
  const [model, setModelInternal] = useState(initialModel);
  const [query, setQuery] = useState("");
  const [topModels, setTopModels] = useState<OpenRouterModelOption[] | null>(
    null,
  );
  const [customMode, setCustomMode] = useState(false);

  const setModel = (next: string) => {
    setModelInternal(next);
    onModelChange(next);
  };

  useEffect(() => {
    let cancelled = false;
    openrouterProvider.fetchTopModels()
      .then((items) => {
        if (cancelled) return;
        setTopModels(items);
        if (items.length > 0 && model === "") {
          setModelInternal(items[0].slug);
          onModelChange(items[0].slug);
        }
      })
      .catch(() => {
        if (!cancelled) setTopModels([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    if (!topModels) return [];
    if (query.trim() === "") return topModels;
    return topModels.filter(
      (m) =>
        fuzzyMatch(query, m.label) ||
        fuzzyMatch(query, m.slug) ||
        fuzzyMatch(query, m.author),
    );
  }, [topModels, query]);

  const canContinue = model.trim() !== "";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canContinue) return;
    onSubmit(model.trim());
  };

  return (
    <form onSubmit={submit} className="flex w-full flex-col items-center gap-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">pick a model</h2>
        <FieldDescription>
          top models on OpenRouter this week.
        </FieldDescription>
      </div>

      <FieldGroup className="w-full gap-3">
        <Field>
          <FieldLabel htmlFor="or-model-search">Model</FieldLabel>
          {customMode ? (
            <>
              <Input
                id="or-model-custom"
                placeholder="provider/model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                autoFocus
              />
              <button
                type="button"
                className="self-start text-[11px] text-muted-foreground hover:text-foreground transition"
                onClick={() => setCustomMode(false)}
              >
                ← back to top models
              </button>
            </>
          ) : (
            <>
              <Input
                id="or-model-search"
                placeholder="search models..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <ModelCardList
                models={filtered}
                selected={model}
                onSelect={setModel}
                loading={topModels === null}
              />
              <button
                type="button"
                className="self-start text-[11px] text-muted-foreground hover:text-foreground transition"
                onClick={() => setCustomMode(true)}
              >
                use a custom slug →
              </button>
            </>
          )}
        </Field>
      </FieldGroup>

      <Button type="submit" className="w-full" disabled={!canContinue}>
        continue
      </Button>
    </form>
  );
}

function ModelCardList({
  models,
  selected,
  onSelect,
  loading,
}: {
  models: OpenRouterModelOption[];
  selected: string;
  onSelect: (slug: string) => void;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex h-[260px] items-center justify-center text-xs text-muted-foreground">
        loading models...
      </div>
    );
  }
  if (models.length === 0) {
    return (
      <div className="flex h-[260px] items-center justify-center text-xs text-muted-foreground">
        no matches
      </div>
    );
  }
  return (
    <div className="flex max-h-[260px] flex-col gap-1.5 overflow-y-auto pr-1 -mr-1">
      {models.map((m) => (
        <ModelCard
          key={m.slug}
          model={m}
          active={m.slug === selected}
          onClick={() => onSelect(m.slug)}
        />
      ))}
    </div>
  );
}

function ModelCard({
  model,
  active,
  onClick,
}: {
  model: OpenRouterModelOption;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-2.5 rounded-xl border p-2 text-left transition-all cursor-pointer ${
        active
          ? "border-primary/60 bg-primary/5 ring-2 ring-primary/30"
          : "border-border bg-input/30 hover:bg-input/60 hover:border-border/80"
      }`}
    >
      <ProviderIcon name={model.author} />
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium">{model.label}</span>
        <span className="truncate text-[11px] text-muted-foreground">
          {model.author}
          {model.context_length
            ? ` · ${formatContextLength(model.context_length)} ctx`
            : ""}
        </span>
      </div>
    </button>
  );
}

function formatContextLength(n: number): string {
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  }
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}
