import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { BellRing } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  getNotificationHistory,
  getNotificationInterruptRules,
  setNotificationInterruptRules,
  type NotificationEvent,
  type NotificationInterruptRule,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

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

// Editor for the agent's notification interrupt rules: active rules render as read-only summaries
// (conditions + a clickable action badge + delete), while a distinct composer below adds new ones.
// First match wins; every change auto-saves and applies live. Exposes addFromNotification so the
// recent-notifications card can seed a rule on click.
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

  useImperativeHandle(
    ref,
    () => ({
      addFromNotification: (seed) => {
        // Refuse while the ruleset is still loading: committing against `null` would treat the
        // unloaded rules as empty and the debounced save would overwrite the user's rules with just
        // this one. The sibling card's make-rule button can fire before this card's fetch resolves.
        if (rules === null) return;
        // Core notifications can never be targeted by a rule — refuse to seed one.
        if (seed.source && isCore(seed.source)) return;
        commit([
          ...rules,
          {
            id: newRuleId(),
            action: "pool",
            source: seed.source,
            type: seed.type,
          },
        ]);
      },
    }),
    [commit, rules],
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
        placeholder={field}
        disabled={disabled}
        className="w-28"
      />
      <ComboboxContent>
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
      <CardContent>
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <BellRing className="size-4 text-muted-foreground" />
            interrupt rules
          </div>
          <p className="text-xs text-muted-foreground">
            decide which notifications interrupt the agent now vs. wait until
            it's idle. first matching rule wins; unmatched notifications keep
            their default. applies live.
          </p>

          {loadError ? (
            <p className="text-xs text-destructive">
              failed to load: {loadError}
            </p>
          ) : rules === null ? (
            <p className="text-xs text-muted-foreground/60">loading…</p>
          ) : (
            <>
              {/* Active rules: read-only summaries with a clickable action badge + delete. */}
              {rules.length === 0 ? (
                <p className="text-xs text-muted-foreground/60">
                  no rules yet.
                </p>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {rules.map((rule, index) => {
                    const conditions = ruleConditions(rule);
                    return (
                      <div
                        key={rule.id}
                        className="flex items-center gap-2 rounded-lg border border-border/60 bg-muted/30 px-2.5 py-1.5"
                      >
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
              )}

              {/* Add composer: visually distinct (dashed) from the active rules above. */}
              <div className="flex flex-col gap-2 rounded-lg bg-background/40 p-2.5">
                <span className="text-[10px] tracking-wide text-muted-foreground/50 uppercase">
                  add a rule
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  {/* Sequential: pick source, then type, then sender — each narrows the next. */}
                  {renderCombobox("source", sourceOptions, false, (value) =>
                    setDraft((d) => ({
                      ...d,
                      source: value,
                      type: "",
                      sender: "",
                    })),
                  )}
                  {renderCombobox("type", typeOptions, !draft.source, (value) =>
                    setDraft((d) => ({ ...d, type: value, sender: "" })),
                  )}
                  {renderCombobox(
                    "sender",
                    senderOptions,
                    !draft.type,
                    (value) => setDraft((d) => ({ ...d, sender: value })),
                  )}
                  {/* keyword is an independent, general condition (a regex) — usable on its own. */}
                  <Input
                    aria-label="keyword"
                    placeholder="keyword (regex)"
                    value={draft.keyword}
                    aria-invalid={keywordRegexError !== null}
                    onChange={(e) =>
                      setDraft((d) => ({ ...d, keyword: e.target.value }))
                    }
                    className="h-8 w-28"
                  />
                  <Select
                    value={draft.action}
                    onValueChange={(v) =>
                      setDraft((d) => ({ ...d, action: v as Draft["action"] }))
                    }
                  >
                    <SelectTrigger
                      size="sm"
                      aria-label="action"
                      className="w-28"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="interrupt">interrupt</SelectItem>
                      <SelectItem value="pool">snooze</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    size="xs"
                    aria-label="add rule"
                    onClick={addDraft}
                    disabled={!draftHasCondition || keywordRegexError !== null}
                    className="ml-auto"
                  >
                    add
                  </Button>
                </div>
                {keywordRegexError !== null ? (
                  <p className="text-[10px] text-destructive">
                    invalid keyword regex: {keywordRegexError}
                  </p>
                ) : null}
              </div>

              {saveError ? (
                <p className="text-[10px] text-destructive">{saveError}</p>
              ) : null}
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
