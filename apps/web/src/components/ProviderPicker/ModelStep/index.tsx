import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup } from "@/components/ui/field";
import { openrouterProvider } from "@/api";

type OpenRouterModelOption = openrouterProvider.OpenRouterModelOption;
import { formatTokens } from "@/lib/format";
import { ProviderIcon } from "../ProviderIcon";
import { ProviderStep } from "../ProviderStep";
import { fuzzyMatch } from "../fuzzy";

export function ModelStep({
  initialModel,
  onModelChange,
  onSubmit,
  models,
  claudeMode,
  allowCustom = true,
  submitLabel = "continue",
  logo,
  onCancel,
}: {
  initialModel: string;
  onModelChange?: (model: string) => void;
  onSubmit: (model: string) => void;
  /// Fixed model list (e.g. Claude opus/sonnet/haiku). When provided, the step
  /// shows just these and skips the OpenRouter fetch, search, and custom-slug.
  models?: OpenRouterModelOption[];
  /// Claude's two-tier picker: two alias buttons plus an expandable live-slug
  /// list. Takes over the render before isFixed/customMode/OpenRouter.
  claudeMode?: {
    aliases: OpenRouterModelOption[];
    liveModels: OpenRouterModelOption[] | null;
  };
  allowCustom?: boolean;
  submitLabel?: string;
  logo?: ReactNode;
  onCancel?: () => void;
}) {
  const isFixed = models !== undefined;
  const [model, setModelInternal] = useState(
    initialModel || (models?.[0]?.slug ?? ""),
  );
  const [query, setQuery] = useState("");
  const [topModels, setTopModels] = useState<OpenRouterModelOption[] | null>(
    models ?? null,
  );
  const [customMode, setCustomMode] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Mirrors the model state so the one-shot fetch below can read the value
  // current at resolve time without depending on it.
  const modelRef = useRef(model);

  const setModel = (next: string) => {
    modelRef.current = next;
    setModelInternal(next);
    onModelChange?.(next);
  };

  useEffect(() => {
    if (isFixed || claudeMode) return;
    let cancelled = false;
    openrouterProvider
      .fetchTopModels()
      .then((items) => {
        if (cancelled) return;
        setTopModels(items);
        const first = items[0];
        if (first !== undefined && modelRef.current === "") {
          modelRef.current = first.slug;
          setModelInternal(first.slug);
          onModelChange?.(first.slug);
        }
      })
      .catch(() => {
        if (!cancelled) setTopModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isFixed, claudeMode, onModelChange]);

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

  return (
    <ProviderStep
      logo={logo}
      title="pick a model"
      subtitle={modelStepSubtitle(claudeMode !== undefined, isFixed)}
      submitLabel={submitLabel}
      submitDisabled={!canContinue}
      onSubmit={() => {
        if (canContinue) onSubmit(model.trim());
      }}
      onCancel={onCancel}
    >
      <FieldGroup className="w-full gap-3">
        <Field>
          {claudeMode ? (
            <ClaudeModelPicker
              claudeMode={claudeMode}
              model={model}
              onSelect={setModel}
              expanded={expanded}
              onToggleExpanded={() => setExpanded((v) => !v)}
            />
          ) : isFixed ? (
            <ModelCardList
              models={filtered}
              selected={model}
              onSelect={setModel}
              loading={false}
            />
          ) : customMode ? (
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
              {allowCustom && (
                <button
                  type="button"
                  className="self-start text-[11px] text-muted-foreground hover:text-foreground transition"
                  onClick={() => setCustomMode(true)}
                >
                  use a custom slug →
                </button>
              )}
            </>
          )}
        </Field>
      </FieldGroup>
    </ProviderStep>
  );
}

function modelStepSubtitle(hasClaudeMode: boolean, isFixed: boolean): string {
  if (hasClaudeMode) return "pick a model.";
  if (isFixed) return "choose a model.";
  return "top models on OpenRouter this week.";
}

// The Claude two-tier control: two primary alias buttons (opus/sonnet) plus an
// expandable live-slug list. Alias and slug selection are mutually exclusive
// because both write the one `model` value via `onSelect`.
function ClaudeModelPicker({
  claudeMode,
  model,
  onSelect,
  expanded,
  onToggleExpanded,
}: {
  claudeMode: {
    aliases: OpenRouterModelOption[];
    liveModels: OpenRouterModelOption[] | null;
  };
  model: string;
  onSelect: (slug: string) => void;
  expanded: boolean;
  onToggleExpanded: () => void;
}) {
  return (
    <div className="flex w-full flex-col gap-3">
      <div className="grid grid-cols-2 gap-2">
        {claudeMode.aliases.map((a) => (
          <button
            key={a.slug}
            type="button"
            onClick={() => onSelect(a.slug)}
            className={`rounded-xl border p-3 text-center text-sm font-medium transition-all cursor-pointer ${
              model === a.slug
                ? "border-primary/60 bg-primary/5 ring-2 ring-primary/30"
                : "border-border bg-input/30 hover:bg-input/60"
            }`}
          >
            {a.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="self-start text-[11px] text-muted-foreground hover:text-foreground transition"
        onClick={onToggleExpanded}
      >
        {expanded ? "← fewer models" : "more models →"}
      </button>
      {expanded && (
        <ModelCardList
          models={claudeMode.liveModels ?? []}
          selected={model}
          onSelect={onSelect}
          loading={claudeMode.liveModels === null}
        />
      )}
    </div>
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
  const price = formatPrice(
    model.input_price,
    model.output_price,
    model.cache_read_price,
  );
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
          {model.note ?? (
            <>
              {model.author}
              {model.context_length
                ? ` · ${formatTokens(model.context_length)} ctx`
                : ""}
              {price ? ` · ${price}` : ""}
            </>
          )}
        </span>
      </div>
    </button>
  );
}

// input/output/cache-read price in USD per million tokens, or null when not
// reported. Cache read is shown only when present and non-zero.
function formatPrice(
  input?: number | null,
  output?: number | null,
  cacheRead?: number | null,
): string | null {
  if (input == null || output == null) return null;
  if (input === 0 && output === 0 && (cacheRead ?? 0) === 0) return "free";
  let price = `${formatUsd(input)}/${formatUsd(output)} Mtok`;
  if (cacheRead != null && cacheRead > 0) {
    price += ` · ${formatUsd(cacheRead)} cache`;
  }
  return price;
}

function formatUsd(price: number): string {
  if (price === 0) return "$0";
  if (price >= 1) return `$${price.toFixed(2).replace(/\.?0+$/, "")}`;
  if (price >= 0.01) return `$${price.toFixed(2)}`;
  // sub-cent: widen precision so tiny cache-read prices don't vanish to $0.00.
  return `$${price.toFixed(4).replace(/\.?0+$/, "")}`;
}
