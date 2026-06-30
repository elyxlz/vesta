import {
  forwardRef,
  type ReactNode,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { GripVertical, ListFilter, Plus, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  getNotificationHistory,
  getNotificationInterruptRules,
  setNotificationInterruptRules,
  type FieldPredicate,
  type NotificationEvent,
  type NotificationInterruptRule,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useLiveNotifications } from "@/hooks/use-live-notifications";
import { cn } from "@/lib/utils";

function uniqueStrings(values: (string | undefined)[]): string[] {
  return [...new Set(values.filter((v): v is string => !!v))];
}

// Stable identity for a notification, to dedupe the REST history against live arrivals.
function notifKey(n: NotificationEvent): string {
  return (
    n.notif_id ||
    `${n.source}|${n.notif_type ?? ""}|${n.sender ?? ""}|${n.summary}`
  );
}

// Core notifications (the agent's own internals) are exempt from rules, so never offer/accept them.
const CORE_SOURCE = "core";
const isCore = (source: string) => source.trim().toLowerCase() === CORE_SOURCE;

const SAVE_DEBOUNCE_MS = 500;

// A stable client-side id for a new rule, so the save round-trip doesn't need to swap ids and
// remount the row being edited. The server keeps any non-empty id it's given.
function newRuleId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `r-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// A field condition being edited: any notification field matched by substring ("is") or regex
// ("matches"), optionally negated. `sender` and `text` are aliases (the sender preset / keyword preset
// seed them); a plain field name (chat_name, chat_type, …) targets that concrete extra.
type DraftPredicate = {
  field: string;
  op: "contains" | "regex";
  value: string;
  negate: boolean;
};

type Draft = {
  source: string;
  type: string;
  predicates: DraftPredicate[];
  action: "interrupt" | "pool";
};
const EMPTY_DRAFT: Draft = {
  source: "",
  type: "",
  predicates: [],
  action: "interrupt",
};

function regexError(pattern: string): string | null {
  try {
    new RegExp(pattern);
    return null;
  } catch (e) {
    return (e as Error).message;
  }
}

// Compile the draft's field conditions into the rule's `match` predicate list (source/type stay
// dedicated). Incomplete rows (no field or no value) are dropped.
function draftToMatch(draft: Draft): FieldPredicate[] {
  return draft.predicates.flatMap((p) => {
    const field = p.field.trim();
    const value = p.value.trim();
    if (!field || !value) return [];
    return [{ field, op: p.op, value, ...(p.negate ? { negate: true } : {}) }];
  });
}

// One predicate -> a read-only badge. The sender/text aliases render under their friendly names;
// any other field shows its name with a relation hint (~ regex, "not" when negated).
function predicateBadge(p: FieldPredicate): { label: string; value: string } {
  if (p.field === "sender" && p.op === "contains" && !p.negate)
    return { label: "sender", value: p.value };
  if (p.field === "text" && p.op === "regex" && !p.negate)
    return { label: "keyword", value: p.value };
  const rel = [p.negate ? "not" : "", p.op === "regex" ? "~" : ""]
    .filter(Boolean)
    .join(" ");
  return { label: p.field, value: rel ? `${rel} ${p.value}` : p.value };
}

// The conditions a rule actually matches on (source/type + every predicate), for the read-only summary.
function ruleConditions(
  rule: NotificationInterruptRule,
): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = [];
  if (rule.source) out.push({ label: "source", value: rule.source });
  if (rule.type) out.push({ label: "type", value: rule.type });
  for (const p of rule.match ?? []) out.push(predicateBadge(p));
  return out;
}

// The notification value a predicate field reads, approximating the engine for the live preview:
// the `sender` alias -> the event's sender, `text` -> its summary, anything else -> a structured extra.
function notifFieldValue(
  n: NotificationEvent,
  field: string,
): string | undefined {
  if (field === "sender") return n.sender;
  if (field === "text") return n.summary;
  return n.fields?.[field];
}

function predicateMatchesNotif(
  p: FieldPredicate,
  n: NotificationEvent,
): boolean {
  const candidate = notifFieldValue(n, p.field);
  let hit = false;
  if (candidate != null) {
    if (p.op === "contains") {
      hit = candidate.toLowerCase().includes(p.value.toLowerCase());
    } else {
      try {
        hit = new RegExp(p.value, "i").test(candidate);
      } catch {
        hit = false;
      }
    }
  }
  return p.negate ? !hit : hit;
}

// Whether a whole rule matches a notification (source/type exact + all predicates), approximating the
// engine for the live preview / shadow check.
function ruleMatchesNotif(
  rule: Pick<NotificationInterruptRule, "source" | "type" | "match">,
  n: NotificationEvent,
): boolean {
  // source/type match case-insensitively, mirroring the engine's _matches.
  if (rule.source && n.source.toLowerCase() !== rule.source.toLowerCase())
    return false;
  if (
    rule.type &&
    (n.notif_type ?? "").toLowerCase() !== rule.type.toLowerCase()
  )
    return false;
  return (rule.match ?? []).every((p) => predicateMatchesNotif(p, n));
}

// How narrowly a rule matches = its condition count. Used only to place a new rule (the engine is
// first-match-wins, never specificity-ranked) so a narrow exception lands above the broad rule it refines.
function specificity(
  rule: Pick<NotificationInterruptRule, "source" | "type" | "match">,
): number {
  return (
    (rule.source ? 1 : 0) + (rule.type ? 1 : 0) + (rule.match?.length ?? 0)
  );
}

// Insert position for a new rule: above the first existing rule that is strictly broader (fewer
// conditions), else at the end. Matches the skill CLI's _placement_index.
function placementIndex(
  rules: NotificationInterruptRule[],
  newRule: Pick<NotificationInterruptRule, "source" | "type" | "match">,
): number {
  const spec = specificity(newRule);
  const i = rules.findIndex((r) => specificity(r) < spec);
  return i === -1 ? rules.length : i;
}

export interface NotificationInterruptRulesHandle {
  addFromNotification: (seed: { source?: string; type?: string }) => void;
}

// A labeled field row in the add-rule dialog: a small heading above its control, with an "· optional"
// hint when the condition can be left blank.
function Field({
  label,
  optional,
  children,
}: {
  label: string;
  optional?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-foreground">
        {label}
        {optional ? (
          <span className="font-normal text-muted-foreground/50">
            {" "}
            · optional
          </span>
        ) : null}
      </span>
      {children}
    </div>
  );
}

// Editor for the agent's notification interrupt rules: active rules render as read-only summaries
// (conditions + a clickable action badge + delete), and a full-width button opens a two-step dialog
// (match conditions -> action) to add a new one. First match wins; every change auto-saves and
// applies live. Exposes addFromNotification so the recent-notifications card can seed a rule on click.
export const NotificationInterruptRulesCard = forwardRef<
  NotificationInterruptRulesHandle,
  object
>(function NotificationInterruptRulesCard(_props, ref) {
  const { name: agentName } = useSelectedAgent();
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The ruleset awaiting a debounced save, so unmount/agent-switch can flush it instead of dropping it.
  const pendingSave = useRef<NotificationInterruptRule[] | null>(null);
  // Last successfully-saved ruleset, so a rejected save can roll the optimistic change back.
  const lastSaved = useRef<NotificationInterruptRule[]>([]);
  const [rules, setRules] = useState<NotificationInterruptRule[] | null>(null);
  const [historyNotifications, setHistoryNotifications] = useState<
    NotificationEvent[]
  >([]);
  // Live arrivals from the agent socket, so suggestions/facets update as notifications come in without
  // a manual refresh. Tolerant of no provider (tests): arrivals is [] and the card is REST-only.
  const { arrivals } = useLiveNotifications();
  // Suggestions read newest-first. Arrivals are oldest-first (the socket appends), so reverse them to
  // put the freshest first, then the fetched history; dedupe keeps the first (freshest) per identity.
  const notifications = useMemo(() => {
    const seen = new Set<string>();
    const merged: NotificationEvent[] = [];
    for (const n of [...[...arrivals].reverse(), ...historyNotifications]) {
      const key = notifKey(n);
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(n);
    }
    return merged;
  }, [arrivals, historyNotifications]);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // The add-rule dialog: a two-step wizard (match conditions -> action).
  const [addOpen, setAddOpen] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  // The dialog's content element, so the combobox popups portal inside it — otherwise they land in
  // body, which the dialog marks inert (pointer-events: none) and the options become unclickable.
  const [dialogEl, setDialogEl] = useState<HTMLElement | null>(null);
  // The rule row currently being dragged, for reordering (null when not dragging).
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!agentName) return;
    let cancelled = false;
    setRules(null);
    setLoadError(null);
    getNotificationInterruptRules(agentName)
      .then((r) => {
        if (cancelled) return;
        setRules(r);
        lastSaved.current = r;
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [agentName]);

  // Recent notifications drive the cascading source -> type -> sender suggestions and the custom-field
  // name/value suggestions. Best-effort: a failure just means no suggestions, never a card error.
  useEffect(() => {
    if (!agentName) return;
    let cancelled = false;
    setHistoryNotifications([]);
    getNotificationHistory(agentName)
      .then((page) => {
        if (!cancelled) setHistoryNotifications(page.notifications);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [agentName]);

  const save = useCallback(
    async (next: NotificationInterruptRule[]) => {
      if (!agentName) return;
      try {
        await setNotificationInterruptRules(agentName, next);
        lastSaved.current = next;
        setSaveError(null);
      } catch (e) {
        // The server rejected the set (e.g. an invalid rule) — roll the optimistic change back to
        // the last accepted ruleset so a rejected rule never lingers in the list.
        setRules(lastSaved.current);
        setSaveError((e as Error).message);
      }
    },
    [agentName],
  );

  // Every change auto-saves after a short debounce; the live endpoint applies it on the next tick.
  const commit = useCallback(
    (next: NotificationInterruptRule[]) => {
      setRules(next);
      pendingSave.current = next;
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        pendingSave.current = null;
        void save(next);
      }, SAVE_DEBOUNCE_MS);
    },
    [save],
  );

  // Flush any debounced edit on unmount or agent switch (e.g. switching settings tabs within the
  // debounce window unmounts this card via Radix Tabs) so an edit is never silently dropped.
  useEffect(
    () => () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      if (pendingSave.current) {
        void save(pendingSave.current);
        pendingSave.current = null;
      }
    },
    [save],
  );

  const toggleAction = (index: number) =>
    commit(
      (rules ?? []).map((rule, i) =>
        i === index
          ? {
              ...rule,
              action: rule.action === "interrupt" ? "pool" : "interrupt",
            }
          : rule,
      ),
    );

  const deleteRule = (index: number) =>
    commit((rules ?? []).filter((_, i) => i !== index));

  // The draft as a rule shape (source/type + compiled match), for the validity, preview, and shadow
  // checks below. Memoized so the per-keystroke preview work downstream has a stable input.
  const draftRule = useMemo(
    () => ({
      source: draft.source.trim() || undefined,
      type: draft.type.trim() || undefined,
      match: draftToMatch(draft),
    }),
    [draft],
  );

  // Require at least one condition: a no-condition rule is a catch-all that would swallow everything.
  // source/type plus any compiled predicate (sender/keyword/custom all fold into match) count.
  const draftHasCondition =
    !!draftRule.source || !!draftRule.type || draftRule.match.length > 0;

  // A "matches" (regex) condition is a regex; surface an invalid pattern inline rather than letting
  // the server reject it.
  const hasRegexError = draft.predicates.some(
    (p) =>
      p.op === "regex" && p.value.trim() !== "" && regexError(p.value.trim()),
  );

  // The recent notifications the draft would catch (approximating the engine against the history we
  // fetched: source/type case-insensitive; predicates over sender/summary/structured fields). Computed
  // once and reused by the match-count and the shadow check, so the scan runs once per keystroke.
  const draftHits = useMemo(
    () =>
      draftHasCondition && !hasRegexError
        ? notifications.filter((n) => ruleMatchesNotif(draftRule, n))
        : null,
    [draftHasCondition, hasRegexError, notifications, draftRule],
  );
  const draftMatchCount = draftHits?.length ?? null;

  // Would the draft be shadowed? At its specificity-placement, if every notification it catches is
  // already caught by a higher-priority rule above it, first-match-wins means it would never fire.
  const draftShadowed = useMemo(() => {
    if (!draftHits || draftHits.length === 0) return false;
    const above = (rules ?? []).slice(
      0,
      placementIndex(rules ?? [], draftRule),
    );
    return draftHits.every((n) => above.some((r) => ruleMatchesNotif(r, n)));
  }, [draftHits, rules, draftRule]);

  const addDraft = () => {
    if (!draftHasCondition || hasRegexError) return;
    setSaveError(null);
    const newRule: NotificationInterruptRule = {
      id: newRuleId(),
      action: draft.action,
      source: draft.source.trim() || undefined,
      type: draft.type.trim() || undefined,
      match: draftToMatch(draft),
    };
    // Auto-place by specificity so a narrow exception isn't shadowed by a broader rule above it.
    const next = [...(rules ?? [])];
    next.splice(placementIndex(next, newRule), 0, newRule);
    commit(next);
    setDraft(EMPTY_DRAFT);
  };

  // Drag-to-reorder: move the rule at `from` to `to`, then persist. Order is priority (first match wins).
  const reorderRule = (from: number, to: number) => {
    const current = rules ?? [];
    if (from === to || from < 0 || to < 0 || from >= current.length) return;
    const next = [...current];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    commit(next);
  };

  // Close the dialog and discard any half-entered draft.
  const closeAdd = () => {
    setAddOpen(false);
    setStep(1);
    setDraft(EMPTY_DRAFT);
  };

  // Commit the drafted rule from step 2, then close (addDraft clears the draft itself).
  const handleAdd = () => {
    addDraft();
    setAddOpen(false);
    setStep(1);
  };

  const step1Valid = draftHasCondition && !hasRegexError;

  useImperativeHandle(
    ref,
    () => ({
      addFromNotification: (seed) => {
        // Core notifications can never be targeted by a rule — refuse to seed one.
        if (seed.source && isCore(seed.source)) return;
        // Open the add-rule dialog pre-filled from the notification, so the user
        // reviews the conditions and picks an action instead of a rule being
        // committed silently. (The dialog only renders once rules have loaded, so
        // its save still has the real ruleset.)
        setDraft({
          ...EMPTY_DRAFT,
          source: seed.source ?? "",
          type: seed.type ?? "",
        });
        setStep(1);
        setAddOpen(true);
      },
    }),
    [],
  );

  // Cascading suggestions: each pick narrows the next. Core is never a rule source. Memoized so typing
  // in an unrelated dialog field doesn't re-scan the whole history every keystroke.
  const sourceOptions = useMemo(
    () =>
      uniqueStrings(notifications.map((n) => n.source)).filter(
        (s) => !isCore(s),
      ),
    [notifications],
  );
  const typeOptions = useMemo(
    () =>
      draft.source
        ? uniqueStrings(
            notifications
              .filter((n) => n.source === draft.source)
              .map((n) => n.notif_type),
          )
        : [],
    [notifications, draft.source],
  );
  // Field-condition suggestions: the structured extra fields seen on notifications, scoped to the
  // picked source when there is one, so the author discovers e.g. `chat_name`. The `sender` and `text`
  // aliases are offered too (the presets seed them, but a hand-typed field condition can reach them).
  const fieldScopedNotifs = useMemo(
    () =>
      draft.source
        ? notifications.filter((n) => n.source === draft.source)
        : notifications,
    [notifications, draft.source],
  );
  const fieldNameOptions = useMemo(
    () =>
      uniqueStrings([
        "sender",
        "text",
        ...fieldScopedNotifs.flatMap((n) => Object.keys(n.fields ?? {})),
      ]),
    [fieldScopedNotifs],
  );
  // Value suggestions for a field: the `sender` alias reads the event's sender; `text` is free regex
  // (no suggestions); any concrete field reads its structured-extra values.
  const predicateValueOptions = (field: string): string[] => {
    if (field === "sender")
      return uniqueStrings(fieldScopedNotifs.map((n) => n.sender));
    if (field === "text" || !field) return [];
    return uniqueStrings(fieldScopedNotifs.map((n) => n.fields?.[field]));
  };

  const updatePredicate = (index: number, patch: Partial<DraftPredicate>) =>
    setDraft((d) => ({
      ...d,
      predicates: d.predicates.map((p, i) =>
        i === index ? { ...p, ...patch } : p,
      ),
    }));
  // Append a field condition. The sender/keyword presets seed the matching alias + op so the common
  // cases stay one click; "field" starts blank for an arbitrary notification field.
  const addPredicate = (preset: "sender" | "keyword" | "field") =>
    setDraft((d) => ({
      ...d,
      predicates: [
        ...d.predicates,
        preset === "sender"
          ? { field: "sender", op: "contains", value: "", negate: false }
          : preset === "keyword"
            ? { field: "text", op: "regex", value: "", negate: false }
            : { field: "", op: "contains", value: "", negate: false },
      ],
    }));
  const removePredicate = (index: number) =>
    setDraft((d) => ({
      ...d,
      predicates: d.predicates.filter((_, i) => i !== index),
    }));

  const renderCombobox = (
    field: "source" | "type",
    items: string[],
    disabled: boolean,
    onSelect: (value: string) => void,
  ) => (
    <Combobox
      items={items}
      value={draft[field] || null}
      onValueChange={(value) =>
        onSelect(typeof value === "string" ? value : "")
      }
      disabled={disabled}
    >
      <ComboboxInput
        aria-label={field}
        placeholder={`any ${field}`}
        disabled={disabled}
        className="w-full"
      />
      <ComboboxContent container={dialogEl}>
        <ComboboxEmpty>no matches</ComboboxEmpty>
        <ComboboxList>
          {(item: string) => (
            <ComboboxItem key={item} value={item}>
              {item}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );

  // A custom field-condition row: a free-text field name (suggested from seen fields via a datalist),
  // an is/matches op toggle, a free-text value (suggested values), a "not" toggle, and remove. Plain
  // inputs + datalists keep arbitrary field names/values typable while still surfacing what's been seen.
  const renderPredicateRow = (p: DraftPredicate, index: number) => {
    const fieldListId = `notif-field-options-${index}`;
    const valueListId = `notif-value-options-${index}`;
    const valueOptions = predicateValueOptions(p.field);
    return (
      <div
        key={index}
        className="flex flex-col gap-1.5 rounded-lg border border-border/60 p-2"
      >
        <div className="flex items-center gap-1.5">
          <Input
            aria-label="custom field"
            placeholder="field (e.g. chat_name)"
            list={fieldNameOptions.length > 0 ? fieldListId : undefined}
            value={p.field}
            onChange={(e) => updatePredicate(index, { field: e.target.value })}
            className="w-full"
          />
          {fieldNameOptions.length > 0 ? (
            <datalist id={fieldListId}>
              {fieldNameOptions.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          ) : null}
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            aria-label="remove field condition"
            onClick={() => removePredicate(index)}
          >
            <X />
          </Button>
        </div>
        <div className="flex items-center gap-1.5">
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={p.op}
            onValueChange={(value) => {
              if (value)
                updatePredicate(index, { op: value as "contains" | "regex" });
            }}
          >
            <ToggleGroupItem value="contains">is</ToggleGroupItem>
            <ToggleGroupItem value="regex">matches</ToggleGroupItem>
          </ToggleGroup>
          <Toggle
            size="sm"
            variant="outline"
            pressed={p.negate}
            onPressedChange={(pressed) =>
              updatePredicate(index, { negate: pressed })
            }
            aria-label="negate field condition"
          >
            not
          </Toggle>
        </div>
        <Input
          aria-label="custom value"
          placeholder={p.op === "regex" ? "regex, e.g. ^proj-" : "value"}
          list={valueOptions.length > 0 ? valueListId : undefined}
          value={p.value}
          aria-invalid={
            p.op === "regex" &&
            p.value.trim() !== "" &&
            regexError(p.value.trim()) !== null
          }
          onChange={(e) => updatePredicate(index, { value: e.target.value })}
          className="w-full"
        />
        {valueOptions.length > 0 ? (
          <datalist id={valueListId}>
            {valueOptions.map((v) => (
              <option key={v} value={v} />
            ))}
          </datalist>
        ) : null}
      </div>
    );
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <ListFilter className="size-4 text-muted-foreground" />
          interrupt rules
        </CardTitle>
        <CardDescription className="text-xs">
          what interrupts {agentName || "the agent"}, and what can wait for a
          quiet moment.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          {loadError ? (
            <p className="text-xs text-destructive">
              failed to load: {loadError}
            </p>
          ) : rules === null ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex items-center gap-2">
                  <div className="flex flex-1 items-center gap-1">
                    <Skeleton className="h-5 w-24 rounded-3xl" />
                    <Skeleton className="h-5 w-16 rounded-3xl" />
                  </div>
                  <Skeleton className="h-5 w-14 rounded-3xl" />
                </div>
              ))}
            </div>
          ) : (
            <>
              {/* Active rules in priority order (first match wins). Drag to reorder; read-only
                  summaries with a clickable action badge + delete. */}
              {rules.length > 0 ? (
                <div className="flex flex-col gap-2">
                  {rules.map((rule, index) => {
                    const conditions = ruleConditions(rule);
                    const draggable = rules.length > 1;
                    return (
                      <div
                        key={rule.id}
                        className={cn(
                          "flex items-center gap-2 rounded-md",
                          dragIndex !== null &&
                            dragIndex !== index &&
                            "outline-dashed outline-1 outline-border/60",
                        )}
                        onDragOver={
                          draggable ? (e) => e.preventDefault() : undefined
                        }
                        onDrop={
                          draggable
                            ? (e) => {
                                e.preventDefault();
                                if (dragIndex !== null)
                                  reorderRule(dragIndex, index);
                                setDragIndex(null);
                              }
                            : undefined
                        }
                      >
                        {draggable ? (
                          <button
                            type="button"
                            draggable
                            aria-label="drag to reorder rule"
                            className="cursor-grab text-muted-foreground/50 hover:text-muted-foreground active:cursor-grabbing"
                            onDragStart={() => setDragIndex(index)}
                            onDragEnd={() => setDragIndex(null)}
                          >
                            <GripVertical className="size-3.5" />
                          </button>
                        ) : null}
                        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
                          {conditions.length === 0 ? (
                            <span className="text-[11px] text-muted-foreground/60">
                              any notification
                            </span>
                          ) : (
                            conditions.map((condition, i) => (
                              <Badge key={i} variant="outline">
                                {condition.label}: {condition.value}
                              </Badge>
                            ))
                          )}
                        </div>
                        <Badge
                          asChild
                          variant={
                            rule.action === "interrupt"
                              ? "default"
                              : "secondary"
                          }
                        >
                          <button
                            type="button"
                            onClick={() => toggleAction(index)}
                            aria-label={`action: ${
                              rule.action === "interrupt"
                                ? "interrupt"
                                : "snooze"
                            }, click to toggle`}
                          >
                            {rule.action === "interrupt"
                              ? "interrupt"
                              : "snooze"}
                          </button>
                        </Badge>
                        <Button
                          size="icon-xs"
                          variant="ghost"
                          aria-label="delete rule"
                          onClick={() => deleteRule(index)}
                        >
                          ✕
                        </Button>
                      </div>
                    );
                  })}
                </div>
              ) : null}

              {/* Add a rule via a two-step dialog so the card stays a clean list + one action. */}
              <Dialog
                open={addOpen}
                onOpenChange={(next) => (next ? setAddOpen(true) : closeAdd())}
              >
                <DialogTrigger asChild>
                  <Button variant="outline" className="w-full">
                    <Plus data-icon="inline-start" />
                    add rule
                  </Button>
                </DialogTrigger>
                <DialogContent
                  className="sm:max-w-[440px]"
                  onOpenAutoFocus={(e) => e.preventDefault()}
                >
                  <DialogHeader>
                    <DialogTitle>add rule</DialogTitle>
                    <DialogDescription>
                      step {step} of 2 ·{" "}
                      {step === 1
                        ? "pick a source, then optionally narrow it down. blank fields match everything."
                        : "choose what happens when a notification matches."}
                    </DialogDescription>
                  </DialogHeader>

                  {step === 1 ? (
                    <div className="flex flex-col gap-3">
                      {/* Reveal-on-fill: source first, then type. Everything else is a field condition. */}
                      <Field label="source">
                        {renderCombobox(
                          "source",
                          sourceOptions,
                          false,
                          (value) =>
                            setDraft((d) => ({
                              ...d,
                              source: value,
                              type: "",
                            })),
                        )}
                      </Field>

                      {draft.source ? (
                        <Field label="type" optional>
                          {renderCombobox("type", typeOptions, false, (value) =>
                            setDraft((d) => ({ ...d, type: value })),
                          )}
                        </Field>
                      ) : null}

                      {/* Conditions: sender / keyword / any field, all uniform predicates. */}
                      {draft.predicates.length > 0 ? (
                        <Field label="conditions" optional>
                          <div className="flex flex-col gap-2">
                            {draft.predicates.map((p, i) =>
                              renderPredicateRow(p, i),
                            )}
                          </div>
                        </Field>
                      ) : null}
                      <div className="flex flex-wrap items-center gap-1.5">
                        {(["sender", "keyword", "field"] as const).map(
                          (preset) => (
                            <Button
                              key={preset}
                              type="button"
                              variant="ghost"
                              size="xs"
                              className="text-muted-foreground"
                              onClick={() => addPredicate(preset)}
                            >
                              <Plus data-icon="inline-start" />
                              {preset}
                            </Button>
                          ),
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2">
                      {(["interrupt", "pool"] as const).map((action) => {
                        const selected = draft.action === action;
                        return (
                          <button
                            key={action}
                            type="button"
                            aria-pressed={selected}
                            onClick={() => setDraft((d) => ({ ...d, action }))}
                            className={cn(
                              "flex flex-col items-start gap-0.5 rounded-xl border p-3 text-left transition-colors",
                              selected
                                ? "border-primary bg-primary/5"
                                : "border-border hover:bg-muted/40",
                            )}
                          >
                            <span className="text-sm font-medium text-foreground">
                              {action === "interrupt" ? "interrupt" : "snooze"}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {action === "interrupt"
                                ? "break in right away"
                                : "wait for a quiet moment"}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}

                  <DialogFooter>
                    {step === 1 ? (
                      <>
                        {hasRegexError ? (
                          <p className="mr-auto min-w-0 self-center truncate text-xs text-destructive">
                            invalid regex in a condition
                          </p>
                        ) : draftShadowed ? (
                          <p className="mr-auto min-w-0 self-center truncate text-xs text-amber-600 dark:text-amber-500">
                            a higher-priority rule already catches these
                          </p>
                        ) : draftMatchCount !== null ? (
                          <p className="mr-auto min-w-0 self-center truncate text-xs text-muted-foreground">
                            {draftMatchCount === 0
                              ? "no recent notifications match yet"
                              : `matches ${draftMatchCount} of your recent notifications`}
                          </p>
                        ) : null}
                        <DialogClose asChild>
                          <Button variant="ghost">cancel</Button>
                        </DialogClose>
                        <Button
                          onClick={() => setStep(2)}
                          disabled={!step1Valid}
                        >
                          next
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button variant="ghost" onClick={() => setStep(1)}>
                          back
                        </Button>
                        <Button onClick={handleAdd}>add rule</Button>
                      </>
                    )}
                  </DialogFooter>
                  {/* Combobox popups portal into this out-of-flow layer (not the
                      DialogContent itself, which is a `grid gap-6`) so an opening
                      dropdown is anchored without adding a grid row that grows the
                      dialog. Still inside the dialog, so options stay clickable. */}
                  <div ref={setDialogEl} className="absolute" />
                </DialogContent>
              </Dialog>

              {saveError ? (
                <p className="text-xs text-destructive">{saveError}</p>
              ) : null}
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
