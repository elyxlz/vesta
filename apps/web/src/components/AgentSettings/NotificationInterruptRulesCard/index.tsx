import {
  forwardRef,
  type ReactNode,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { ListFilter, Plus } from "lucide-react";
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
  type NotificationEvent,
  type NotificationInterruptRule,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { cn } from "@/lib/utils";

function uniqueStrings(values: (string | undefined)[]): string[] {
  return [...new Set(values.filter((v): v is string => !!v))];
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

const FIELDS: {
  key: "source" | "type" | "sender" | "keyword";
  label: string;
}[] = [
  { key: "source", label: "source" },
  { key: "type", label: "type" },
  { key: "sender", label: "sender" },
  { key: "keyword", label: "keyword" },
];

type Draft = {
  source: string;
  type: string;
  sender: string;
  keyword: string;
  action: "interrupt" | "pool";
};
const EMPTY_DRAFT: Draft = {
  source: "",
  type: "",
  sender: "",
  keyword: "",
  action: "interrupt",
};

// The conditions a rule actually matches on (set fields only), for the read-only summary.
function ruleConditions(
  rule: NotificationInterruptRule,
): { label: string; value: string }[] {
  return FIELDS.flatMap((field) => {
    const value = rule[field.key];
    return value ? [{ label: field.label, value }] : [];
  });
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
  const [notifications, setNotifications] = useState<NotificationEvent[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // The add-rule dialog: a two-step wizard (match conditions -> action).
  const [addOpen, setAddOpen] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  // The dialog's content element, so the combobox popups portal inside it — otherwise they land in
  // body, which the dialog marks inert (pointer-events: none) and the options become unclickable.
  const [dialogEl, setDialogEl] = useState<HTMLElement | null>(null);

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

  // Recent notifications drive the cascading source -> type -> sender suggestions. Best-effort: a
  // failure just means no suggestions, never a card error.
  useEffect(() => {
    if (!agentName) return;
    let cancelled = false;
    setNotifications([]);
    getNotificationHistory(agentName)
      .then((page) => {
        if (!cancelled) setNotifications(page.notifications);
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

  // Require at least one condition: a no-condition rule is a catch-all that would swallow everything.
  const draftHasCondition = FIELDS.some(
    (field) => draft[field.key].trim() !== "",
  );

  // keyword is a regex; surface an invalid pattern inline rather than letting the server reject it.
  const keywordRegexError = (() => {
    const pattern = draft.keyword.trim();
    if (!pattern) return null;
    try {
      new RegExp(pattern);
      return null;
    } catch (e) {
      return (e as Error).message;
    }
  })();

  // Live preview: how many recent notifications the drafted conditions would catch, so the rule's
  // effect is visible before it's added. Approximates the engine (exact source/type/sender, regex
  // keyword over the summary) against the history we already fetched for suggestions.
  const draftMatchCount =
    draftHasCondition && keywordRegexError === null
      ? (() => {
          const pattern = draft.keyword.trim();
          const keywordRe = pattern ? new RegExp(pattern, "i") : null;
          return notifications.filter((n) => {
            if (draft.source && n.source !== draft.source) return false;
            if (draft.type && n.notif_type !== draft.type) return false;
            if (draft.sender && n.sender !== draft.sender) return false;
            if (keywordRe && !keywordRe.test(n.summary)) return false;
            return true;
          }).length;
        })()
      : null;

  const addDraft = () => {
    if (!draftHasCondition || keywordRegexError !== null) return;
    setSaveError(null);
    commit([
      ...(rules ?? []),
      {
        id: newRuleId(),
        action: draft.action,
        source: draft.source.trim() || undefined,
        type: draft.type.trim() || undefined,
        sender: draft.sender.trim() || undefined,
        keyword: draft.keyword.trim() || undefined,
      },
    ]);
    setDraft(EMPTY_DRAFT);
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

  const step1Valid = draftHasCondition && keywordRegexError === null;

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
              {/* Active rules: read-only summaries with a clickable action badge + delete. */}
              {rules.length > 0 ? (
                <div className="flex flex-col gap-2">
                  {rules.map((rule, index) => {
                    const conditions = ruleConditions(rule);
                    return (
                      <div key={rule.id} className="flex items-center gap-2">
                        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
                          {conditions.length === 0 ? (
                            <span className="text-[11px] text-muted-foreground/60">
                              any notification
                            </span>
                          ) : (
                            conditions.map((condition) => (
                              <Badge key={condition.label} variant="outline">
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
