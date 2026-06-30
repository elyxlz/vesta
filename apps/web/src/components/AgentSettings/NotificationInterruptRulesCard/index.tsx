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

// A custom field condition being edited: any notification field (chat_name, chat_type, …) matched
// by substring ("is") or regex ("matches"), optionally negated. `sender`/`keyword` are separate
// ergonomic shortcuts that compile to the same kind of predicate.
type DraftPredicate = {
  field: string;
  op: "contains" | "regex";
  value: string;
  negate: boolean;
};

type Draft = {
  source: string;
  type: string;
  sender: string;
  keyword: string;
  predicates: DraftPredicate[];
  action: "interrupt" | "pool";
};
const EMPTY_DRAFT: Draft = {
  source: "",
  type: "",
  sender: "",
  keyword: "",
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

// Compile a draft's shortcuts + custom rows into the rule's `match` predicate list (source/type stay
// dedicated). sender = substring over the identity alias; keyword = regex over the body/message text.
function draftToMatch(draft: Draft): FieldPredicate[] {
  const match: FieldPredicate[] = [];
  const sender = draft.sender.trim();
  if (sender) match.push({ field: "sender", op: "contains", value: sender });
  const keyword = draft.keyword.trim();
  if (keyword) match.push({ field: "text", op: "regex", value: keyword });
  for (const p of draft.predicates) {
    const field = p.field.trim();
    const value = p.value.trim();
    if (field && value)
      match.push({
        field,
        op: p.op,
        value,
        ...(p.negate ? { negate: true } : {}),
      });
  }
  return match;
}

// One predicate -> a read-only badge. The sender/text aliases render under their friendly names;
// any other field shows its name with a relation hint (~ regex, "not" when negated).
function predicateBadge(p: FieldPredicate): { label: string; value: string } {
  if (p.field === "sender" && p.op === "contains" && !p.negate)
    return { label: "sender", value: p.value };
  if (p.field === "text" && p.op === "regex" && !p.negate)
    return { label: "keyword", value: p.value };
  const rel = p.negate
    ? p.op === "regex"
      ? "not ~"
      : "not"
    : p.op === "regex"
      ? "~"
      : "";
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

  // A completed custom predicate row (both field and value filled in).
  const completePredicates = draft.predicates.filter(
    (p) => p.field.trim() !== "" && p.value.trim() !== "",
  );

  // Require at least one condition: a no-condition rule is a catch-all that would swallow everything.
  const draftHasCondition =
    draft.source.trim() !== "" ||
    draft.type.trim() !== "" ||
    draft.sender.trim() !== "" ||
    draft.keyword.trim() !== "" ||
    completePredicates.length > 0;

  // keyword + any regex custom predicate are regexes; surface an invalid pattern inline rather than
  // letting the server reject it.
  const keywordRegexError = draft.keyword.trim()
    ? regexError(draft.keyword.trim())
    : null;
  const predicateRegexError = draft.predicates.some(
    (p) =>
      p.op === "regex" && p.value.trim() !== "" && regexError(p.value.trim()),
  );
  const hasRegexError = keywordRegexError !== null || predicateRegexError;

  // The draft as a rule shape, for the live preview + shadow check below.
  const draftRule = {
    source: draft.source.trim() || undefined,
    type: draft.type.trim() || undefined,
    match: draftToMatch(draft),
  };

  // Live preview: how many recent notifications the drafted conditions would catch, so the rule's
  // effect is visible before it's added. Approximates the engine against the history we already
  // fetched (source/type case-insensitive; predicates over sender/summary/structured fields).
  const draftMatchCount =
    draftHasCondition && !hasRegexError
      ? notifications.filter((n) => ruleMatchesNotif(draftRule, n)).length
      : null;

  // Would the draft be shadowed? At its specificity-placement, if every recent notification it catches
  // is already caught by a higher-priority rule above it, first-match-wins means it would never fire.
  const draftShadowed = (() => {
    if (!draftHasCondition || hasRegexError) return false;
    const hits = notifications.filter((n) => ruleMatchesNotif(draftRule, n));
    if (hits.length === 0) return false;
    const above = (rules ?? []).slice(
      0,
      placementIndex(rules ?? [], draftRule),
    );
    return hits.every((n) => above.some((r) => ruleMatchesNotif(r, n)));
  })();

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

  // Cascading suggestions: each pick narrows the next. Core is never a rule source.
  const sourceOptions = uniqueStrings(
    notifications.map((n) => n.source),
  ).filter((s) => !isCore(s));
  const typeOptions = draft.source
    ? uniqueStrings(
        notifications
          .filter((n) => n.source === draft.source)
          .map((n) => n.notif_type),
      )
    : [];
  const senderOptions =
    draft.source && draft.type
      ? uniqueStrings(
          notifications
            .filter(
              (n) => n.source === draft.source && n.notif_type === draft.type,
            )
            .map((n) => n.sender),
        )
      : [];

  // Custom-field suggestions: the structured extra fields (and their values) seen on notifications,
  // scoped to the picked source when there is one, so the author discovers e.g. `chat_name`.
  const fieldScopedNotifs = draft.source
    ? notifications.filter((n) => n.source === draft.source)
    : notifications;
  const fieldNameOptions = uniqueStrings(
    fieldScopedNotifs.flatMap((n) => Object.keys(n.fields ?? {})),
  );
  const fieldValueOptions = (field: string) =>
    field ? uniqueStrings(fieldScopedNotifs.map((n) => n.fields?.[field])) : [];

  const updatePredicate = (index: number, patch: Partial<DraftPredicate>) =>
    setDraft((d) => ({
      ...d,
      predicates: d.predicates.map((p, i) =>
        i === index ? { ...p, ...patch } : p,
      ),
    }));
  const addPredicate = () =>
    setDraft((d) => ({
      ...d,
      predicates: [
        ...d.predicates,
        { field: "", op: "contains", value: "", negate: false },
      ],
    }));
  const removePredicate = (index: number) =>
    setDraft((d) => ({
      ...d,
      predicates: d.predicates.filter((_, i) => i !== index),
    }));

  const renderCombobox = (
    field: "source" | "type" | "sender",
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
    const valueOptions = fieldValueOptions(p.field);
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
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="flex items-center gap-1.5">
          {(["contains", "regex"] as const).map((op) => (
            <Button
              key={op}
              type="button"
              size="xs"
              variant={p.op === op ? "secondary" : "ghost"}
              aria-pressed={p.op === op}
              onClick={() => updatePredicate(index, { op })}
            >
              {op === "contains" ? "is" : "matches"}
            </Button>
          ))}
          <Button
            type="button"
            size="xs"
            variant={p.negate ? "secondary" : "ghost"}
            aria-pressed={p.negate}
            aria-label="negate field condition"
            onClick={() => updatePredicate(index, { negate: !p.negate })}
          >
            not
          </Button>
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
                  <Button variant="outline" className="w-full gap-1.5">
                    <Plus className="size-4" />
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
                      {/* Reveal-on-fill: source first, then type, then sender — each narrows the next. */}
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
                              sender: "",
                            })),
                        )}
                      </Field>

                      {draft.source ? (
                        <Field label="type" optional>
                          {renderCombobox("type", typeOptions, false, (value) =>
                            setDraft((d) => ({
                              ...d,
                              type: value,
                              sender: "",
                            })),
                          )}
                        </Field>
                      ) : null}

                      {draft.type ? (
                        <Field label="sender" optional>
                          {renderCombobox(
                            "sender",
                            senderOptions,
                            false,
                            (value) =>
                              setDraft((d) => ({ ...d, sender: value })),
                          )}
                        </Field>
                      ) : null}

                      {/* keyword is an independent, general condition (a regex) — usable on its own. */}
                      <Field label="keyword" optional>
                        <Input
                          aria-label="keyword"
                          placeholder="regex, e.g. urgent|asap"
                          value={draft.keyword}
                          aria-invalid={keywordRegexError !== null}
                          onChange={(e) =>
                            setDraft((d) => ({ ...d, keyword: e.target.value }))
                          }
                          className="w-full"
                        />
                      </Field>

                      {/* General field conditions: target any notification field (chat_name, …). */}
                      {draft.predicates.length > 0 ? (
                        <Field label="field conditions" optional>
                          <div className="flex flex-col gap-2">
                            {draft.predicates.map((p, i) =>
                              renderPredicateRow(p, i),
                            )}
                          </div>
                        </Field>
                      ) : null}
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        className="self-start gap-1 text-muted-foreground"
                        onClick={addPredicate}
                      >
                        <Plus className="size-3.5" />
                        add field condition
                      </Button>
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
                        {keywordRegexError !== null ? (
                          <p className="mr-auto min-w-0 self-center truncate text-xs text-destructive">
                            invalid keyword regex: {keywordRegexError}
                          </p>
                        ) : predicateRegexError ? (
                          <p className="mr-auto min-w-0 self-center truncate text-xs text-destructive">
                            invalid field regex
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
