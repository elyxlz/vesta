import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDownIcon, ChevronUpIcon, SearchIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Field, FieldGroup } from "@/components/ui/field";
import { openrouterProvider } from "@/api";

type OpenRouterModelOption = openrouterProvider.OpenRouterModelOption;
import { formatTokens } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useScrollFade } from "@/hooks/use-scroll-fade";
import {
  glassFrost,
  glassHover,
  glassSelected,
} from "@/components/NewAgent/glass";
import { ProviderIcon } from "../ProviderIcon";
import { ProviderStep } from "../ProviderStep";
import { fuzzyMatch } from "../fuzzy";
import { CLAUDE_ALIASES } from "../model-options";
import { canonicalClaudeModel } from "@vesta/core";

export function ModelStep({
  initialModel,
  onModelChange,
  onSubmit,
  models,
  claudeLiveModels,
  submitLabel = "continue",
  logo,
  onBack,
}: {
  initialModel: string;
  onModelChange?: (model: string) => void;
  onSubmit: (model: string) => void;
  /// Fixed model list (e.g. Z.AI's). When provided, the step shows just these
  /// and skips the OpenRouter fetch and search.
  models?: OpenRouterModelOption[];
  /// Claude's two-tier picker: the alias buttons plus this expandable live-slug
  /// list (null while loading). Takes over the render when not undefined.
  claudeLiveModels?: OpenRouterModelOption[] | null;
  submitLabel?: string;
  logo?: ReactNode;
  onBack?: () => void;
}) {
  const isFixed = models !== undefined;
  const isClaude = claudeLiveModels !== undefined;
  const [model, setModelInternal] = useState(() => {
    const initial = initialModel || (models?.[0]?.slug ?? "");
    return isClaude ? canonicalClaudeModel(initial) : initial;
  });
  const [query, setQuery] = useState("");
  const [topModels, setTopModels] = useState<OpenRouterModelOption[] | null>(
    models ?? null,
  );

  // Mirrors the model state so the one-shot fetch below can read the value
  // current at resolve time without depending on it.
  const modelRef = useRef(model);

  const setModel = (next: string) => {
    modelRef.current = next;
    setModelInternal(next);
    onModelChange?.(next);
  };

  useEffect(() => {
    if (isFixed || isClaude) return;
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
  }, [isFixed, isClaude, onModelChange]);

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
      subtitle={
        isClaude || isFixed
          ? "choose a model."
          : "top models on OpenRouter this week."
      }
      submitLabel={submitLabel}
      submitDisabled={!canContinue}
      onSubmit={() => {
        if (canContinue) onSubmit(model.trim());
      }}
      onBack={onBack}
    >
      <FieldGroup className="w-full gap-3">
        <Field>
          {claudeLiveModels !== undefined ? (
            <ClaudeModelPicker
              liveModels={claudeLiveModels}
              model={model}
              onSelect={setModel}
            />
          ) : isFixed ? (
            <ModelCardList
              models={filtered}
              selected={model}
              onSelect={setModel}
              loading={false}
            />
          ) : (
            <>
              <div className="relative w-full">
                <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="or-model-search"
                  placeholder="search models..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-11 pl-10"
                />
              </div>
              <ModelCardList
                models={filtered}
                selected={model}
                onSelect={setModel}
                loading={topModels === null}
              />
            </>
          )}
        </Field>
      </FieldGroup>
    </ProviderStep>
  );
}

// The Claude two-tier control: two primary alias buttons (opus/sonnet) plus an
// expandable live-slug list. Alias and slug selection are mutually exclusive
// because both write the one `model` value via `onSelect`.
function ClaudeModelPicker({
  liveModels,
  model,
  onSelect,
}: {
  liveModels: OpenRouterModelOption[] | null;
  model: string;
  onSelect: (slug: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const tileBase =
    "flex cursor-pointer items-center justify-center rounded-2xl [corner-shape:squircle] p-3 text-center text-sm font-medium";
  return (
    <div className="flex w-full flex-col gap-3">
      {/* Opus and Sonnet fill the row; a compact tile expands the live list. */}
      <div className="flex gap-2">
        {CLAUDE_ALIASES.map((a) => (
          <button
            key={a.slug}
            type="button"
            onClick={() => onSelect(a.slug)}
            className={cn(
              tileBase,
              "flex-1",
              glassFrost,
              glassHover,
              model === a.slug && glassSelected,
            )}
          >
            {a.label}
          </button>
        ))}
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={expanded ? "fewer models" : "more models"}
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            tileBase,
            "shrink-0 text-muted-foreground",
            glassFrost,
            glassHover,
          )}
        >
          {expanded ? (
            <ChevronUpIcon className="size-4" />
          ) : (
            <ChevronDownIcon className="size-4" />
          )}
        </button>
      </div>
      {expanded && (
        <ModelCardList
          models={liveModels ?? []}
          selected={model}
          onSelect={onSelect}
          loading={liveModels === null}
          showIcon={false}
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
  showIcon = true,
}: {
  models: OpenRouterModelOption[];
  selected: string;
  onSelect: (slug: string) => void;
  loading: boolean;
  showIcon?: boolean;
}) {
  const fade = useScrollFade<HTMLDivElement>();
  const { update } = fade;
  // The box height is fixed, so a resize observer never fires; recompute the
  // fade when the list contents change (search filter, catalog load).
  useEffect(() => {
    update();
  }, [models, update]);

  if (loading) {
    return <ModelListSkeleton showIcon={showIcon} />;
  }
  if (models.length === 0) {
    return (
      <div className="flex h-[260px] items-center justify-center text-xs text-muted-foreground">
        no matches
      </div>
    );
  }
  return (
    <div
      ref={fade.ref}
      style={fade.style}
      className="flex max-h-[260px] flex-col gap-1.5 overflow-y-auto pr-1 -mr-1"
    >
      {models.map((m) => (
        <ModelCard
          key={m.slug}
          model={m}
          active={m.slug === selected}
          showIcon={showIcon}
          onClick={() => onSelect(m.slug)}
        />
      ))}
    </div>
  );
}

// Card-shaped placeholders that fill the list area while the catalog loads, so
// the load reads as model cards resolving in place rather than a text spinner.
const SKELETON_ROWS = [
  { label: "w-2/5", detail: "w-3/5" },
  { label: "w-1/2", detail: "w-2/5" },
  { label: "w-1/3", detail: "w-1/2" },
  { label: "w-2/5", detail: "w-1/3" },
  { label: "w-1/2", detail: "w-3/5" },
];

function ModelListSkeleton({ showIcon }: { showIcon: boolean }) {
  return (
    <div className="flex max-h-[260px] flex-col gap-1.5 overflow-hidden">
      {SKELETON_ROWS.map((row, i) => (
        <div
          key={i}
          className={cn(
            "flex items-center gap-2.5 rounded-2xl [corner-shape:squircle] px-2.5 py-1.5",
            glassFrost,
          )}
        >
          {showIcon && <Skeleton className="size-7 shrink-0 rounded-full" />}
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <Skeleton className={cn("h-3.5 rounded-md", row.label)} />
            <Skeleton className={cn("h-2.5 rounded-md", row.detail)} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ModelCard({
  model,
  active,
  showIcon,
  onClick,
}: {
  model: OpenRouterModelOption;
  active: boolean;
  showIcon: boolean;
  onClick: () => void;
}) {
  const price = formatPrice(
    model.input_price,
    model.output_price,
    model.cache_read_price,
  );
  // Author is carried by the icon, not repeated as text; the detail line shows
  // only context + price, and is dropped when neither is known.
  const detail = [
    model.context_length ? `${formatTokens(model.context_length)} ctx` : null,
    price,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex cursor-pointer items-center gap-2.5 rounded-2xl [corner-shape:squircle] px-2.5 py-1.5 text-left",
        glassFrost,
        glassHover,
        active && glassSelected,
      )}
    >
      {showIcon && <ProviderIcon name={model.author} className="size-7" />}
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium">{model.label}</span>
        {detail && (
          <span className="truncate text-[11px] text-muted-foreground">
            {detail}
          </span>
        )}
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
