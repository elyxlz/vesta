import { useCallback, useEffect, useRef, useState } from "react";
import { GripVertical, ListFilter } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@/components/ui/item";
import {
  getNotificationInterruptRules,
  setNotificationInterruptRules,
  type FieldPredicate,
  type NotificationInterruptRule,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { cn } from "@/lib/utils";

const SAVE_DEBOUNCE_MS = 500;

type RuleAction = NotificationInterruptRule["action"];

// The action badge cycles on click. interrupt/snooze only change *timing*; trash is different in kind:
// it drops the notification entirely (it never reaches the agent), so it reads as destructive.
const ACTION_CYCLE: Record<RuleAction, RuleAction> = {
  interrupt: "snooze",
  snooze: "trash",
  trash: "interrupt",
};
const ACTION_LABEL: Record<RuleAction, string> = {
  interrupt: "interrupt",
  snooze: "snooze",
  trash: "trash",
};
const ACTION_BADGE_VARIANT: Record<
  RuleAction,
  "default" | "outline" | "destructive"
> = {
  interrupt: "default",
  snooze: "outline",
  trash: "destructive",
};

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

// The conditions a rule matches on (source/type + every predicate), for the read-only summary.
function ruleConditions(
  rule: NotificationInterruptRule,
): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = [];
  if (rule.source) out.push({ label: "source", value: rule.source });
  if (rule.type) out.push({ label: "type", value: rule.type });
  for (const p of rule.match ?? []) out.push(predicateBadge(p));
  return out;
}

// Editor for the agent's notification interrupt rules: active rules render as read-only summaries
// (conditions + a clickable action badge + drag-to-reorder + delete). Rules are authored by asking the
// agent in chat; this card manages the existing ones. First match wins; every change auto-saves live.
export function NotificationInterruptRulesCard() {
  const { name: agentName } = useSelectedAgent();
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The ruleset awaiting a debounced save, so unmount/agent-switch can flush it instead of dropping it.
  const pendingSave = useRef<NotificationInterruptRule[] | null>(null);
  // Last successfully-saved ruleset, so a rejected save can roll the optimistic change back.
  const lastSaved = useRef<NotificationInterruptRule[]>([]);
  const [rules, setRules] = useState<NotificationInterruptRule[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // The rule row currently being dragged, for reordering (null when not dragging).
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  // Index of the rule a click is about to move into trash, pending confirmation (null = no dialog).
  const [confirmTrashIndex, setConfirmTrashIndex] = useState<number | null>(
    null,
  );

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
      .catch((e: unknown) => {
        if (!cancelled)
          setLoadError(e instanceof Error ? e.message : String(e));
      });
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
        // The server rejected the set — roll the optimistic change back to the last accepted ruleset.
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

  // Flush any debounced edit on unmount or agent switch so an edit is never silently dropped.
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

  const applyAction = (index: number, action: RuleAction) =>
    commit(
      (rules ?? []).map((rule, i) =>
        i === index ? { ...rule, action } : rule,
      ),
    );

  const cycleAction = (index: number) => {
    const rule = (rules ?? [])[index];
    if (!rule) return;
    const next = ACTION_CYCLE[rule.action];
    // Trash drops matching notifications entirely (they never reach the agent) and auto-saves, so
    // confirm before stepping into it. Every other transition — including downgrading out of trash —
    // is only a timing change and applies immediately.
    if (next === "trash") {
      setConfirmTrashIndex(index);
      return;
    }
    applyAction(index, next);
  };

  const deleteRule = (index: number) =>
    commit((rules ?? []).filter((_, i) => i !== index));

  // Drag-to-reorder: move the rule at `from` to `to`, then persist. Order is priority (first match wins).
  const reorderRule = (from: number, to: number) => {
    const current = rules ?? [];
    if (from === to || from < 0 || to < 0 || from >= current.length) return;
    const next = [...current];
    const [moved] = next.splice(from, 1);
    if (moved === undefined) return;
    next.splice(to, 0, moved);
    commit(next);
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <ListFilter className="size-4 text-muted-foreground" />
          interrupt rules
        </CardTitle>
        <CardDescription>
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
                <ItemGroup>
                  {rules.map((rule, index) => {
                    const conditions = ruleConditions(rule);
                    const draggable = rules.length > 1;
                    return (
                      <Item
                        key={rule.id}
                        variant="muted"
                        size="sm"
                        className={cn(
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
                        <ItemActions>
                          <Badge
                            asChild
                            variant={ACTION_BADGE_VARIANT[rule.action]}
                          >
                            <button
                              type="button"
                              onClick={() => cycleAction(index)}
                              aria-label={`action: ${ACTION_LABEL[rule.action]}, click to change`}
                            >
                              {ACTION_LABEL[rule.action]}
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
                        </ItemActions>
                      </Item>
                    );
                  })}
                </ItemGroup>
              ) : null}

              {/* Rules are authored by the agent: ask it in chat instead of a form. */}
              <Item variant="muted" size="sm" className="items-start">
                <ItemContent className="gap-0.5">
                  <ItemTitle>
                    {rules.length === 0 ? "no rules yet" : "add a rule"}
                  </ItemTitle>
                  <ItemDescription className="line-clamp-none">
                    just ask {agentName || "the agent"} — e.g.{" "}
                    <span className="text-foreground">
                      "don't let Twitter interrupt you"
                    </span>{" "}
                    or{" "}
                    <span className="text-foreground">
                      "snooze the Bride Squad group chat"
                    </span>
                    .
                  </ItemDescription>
                </ItemContent>
              </Item>

              {saveError ? (
                <p className="text-xs text-destructive">{saveError}</p>
              ) : null}
            </>
          )}
        </div>
      </CardContent>
      <AlertDialog
        open={confirmTrashIndex !== null}
        onOpenChange={(next) => {
          if (!next) setConfirmTrashIndex(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>trash matching notifications?</AlertDialogTitle>
            <AlertDialogDescription>
              a trash rule drops every matching notification entirely — they
              never reach {agentName || "the agent"} and create no turn. they
              still show in history, and you can change the rule back anytime.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={(e) => {
                e.preventDefault();
                if (confirmTrashIndex !== null)
                  applyAction(confirmTrashIndex, "trash");
                setConfirmTrashIndex(null);
              }}
            >
              trash them
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
