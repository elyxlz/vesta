import { useState } from "react";
import { Alert, Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Crypto from "expo-crypto";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getNotificationRules, setNotificationRules } from "@/api/endpoints";
import type {
  FieldPredicate,
  NotificationInterruptRule,
} from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, FormRow, FormSection } from "@/components/ui/Form";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

type RuleAction = NotificationInterruptRule["action"];

const actionOrder: RuleAction[] = ["interrupt", "snooze", "trash"];

function describePredicate(predicate: FieldPredicate): string {
  const relation = predicate.op === "regex" ? "matches" : "contains";
  return `${predicate.field} ${predicate.negate ? "does not " : ""}${relation} ${predicate.value}`;
}

function RuleCard({
  rule,
  first,
  last,
  onMove,
  onCycle,
  onDelete,
}: {
  rule: NotificationInterruptRule;
  first: boolean;
  last: boolean;
  onMove: (direction: -1 | 1) => void;
  onCycle: () => void;
  onDelete: () => void;
}) {
  const { colors } = usePreferences();
  const conditions = [
    rule.source ? `source is ${rule.source}` : "any source",
    rule.type ? `type is ${rule.type}` : null,
    ...(rule.match ?? []).map(describePredicate),
  ].filter((value): value is string => value !== null);
  const actionColor =
    rule.action === "trash"
      ? colors.danger
      : rule.action === "interrupt"
        ? colors.warning
        : colors.accent;

  return (
    <Card style={styles.rule}>
      <View style={styles.ruleTop}>
        <View style={styles.conditions}>
          {conditions.map((condition) => (
            <Text key={condition} style={[styles.condition, { color: colors.secondaryText }]}>
              {condition}
            </Text>
          ))}
        </View>
        <View style={styles.orderButtons}>
          <Pressable
            accessibilityLabel="Move rule earlier"
            disabled={first}
            onPress={() => onMove(-1)}
            hitSlop={8}
            style={{ opacity: first ? 0.25 : 1 }}
          >
            <Ionicons name="chevron-up" size={20} color={colors.secondaryText} />
          </Pressable>
          <Pressable
            accessibilityLabel="Move rule later"
            disabled={last}
            onPress={() => onMove(1)}
            hitSlop={8}
            style={{ opacity: last ? 0.25 : 1 }}
          >
            <Ionicons name="chevron-down" size={20} color={colors.secondaryText} />
          </Pressable>
        </View>
      </View>
      <View style={styles.ruleActions}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Action ${rule.action}. Tap to change.`}
          onPress={onCycle}
          style={[styles.badge, { backgroundColor: `${actionColor}20` }]}
        >
          <Text style={[styles.badgeText, { color: actionColor }]}>{rule.action}</Text>
        </Pressable>
        <Pressable accessibilityLabel="Delete rule" onPress={onDelete} hitSlop={8}>
          <Ionicons name="trash-outline" size={19} color={colors.danger} />
        </Pressable>
      </View>
    </Card>
  );
}

function RuleComposer({ onAdd, busy }: { onAdd: (rule: NotificationInterruptRule) => void; busy: boolean }) {
  const [source, setSource] = useState("");
  const [type, setType] = useState("");
  const [sender, setSender] = useState("");
  const [keyword, setKeyword] = useState("");
  const [action, setAction] = useState<RuleAction>("interrupt");

  const chooseAction = () => {
    Alert.alert("Rule action", "The first matching rule wins.", [
      ...actionOrder.map((value) => ({
        text: value,
        onPress: () => setAction(value),
      })),
      { text: "Cancel", style: "cancel" },
    ]);
  };
  const add = () => {
    const predicates: FieldPredicate[] = [];
    if (sender.trim()) {
      predicates.push({ field: "sender", op: "contains", value: sender.trim() });
    }
    if (keyword.trim()) {
      predicates.push({ field: "text", op: "regex", value: keyword.trim() });
    }
    onAdd({
      id: Crypto.randomUUID(),
      source: source.trim() || null,
      type: type.trim() || null,
      match: predicates,
      action,
    });
    setSource("");
    setType("");
    setSender("");
    setKeyword("");
    setAction("interrupt");
  };

  return (
    <Card>
      <Field label="Source" description="Optional, for example gmail or slack." value={source} onChangeText={setSource} autoCapitalize="none" />
      <Field label="Notification type" description="Optional provider event type." value={type} onChangeText={setType} autoCapitalize="none" />
      <Field label="Sender contains" value={sender} onChangeText={setSender} autoCapitalize="none" />
      <Field label="Text matches" description="Optional regular expression." value={keyword} onChangeText={setKeyword} autoCapitalize="none" />
      <FormRow label="Action" value={action} onPress={chooseAction} />
      <Button disabled={busy} icon="add" onPress={add}>Add rule</Button>
    </Card>
  );
}

export function NotificationsSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const query = useQuery({
    queryKey: ["notification-rules", name],
    queryFn: () => getNotificationRules(api, name),
  });
  const save = useMutation({
    mutationFn: (rules: NotificationInterruptRule[]) => setNotificationRules(api, name, rules),
    onMutate: async (rules) => {
      await queryClient.cancelQueries({ queryKey: ["notification-rules", name] });
      const previous = queryClient.getQueryData<NotificationInterruptRule[]>(["notification-rules", name]);
      queryClient.setQueryData(["notification-rules", name], rules);
      return { previous };
    },
    onError: (_error, _rules, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["notification-rules", name], context.previous);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["notification-rules", name] });
    },
  });

  if (query.isLoading) return <LoadingState label="Loading notification rules…" />;
  if (!query.data) {
    return <ErrorState message="Notification rules are unavailable." retry={() => void query.refetch()} />;
  }

  const rules = query.data;
  const update = (next: NotificationInterruptRule[]) => save.mutate(next);
  return (
    <>
      <FormSection
        title="Priority rules"
        footer="Rules are checked from top to bottom. Interrupt delivers now, snooze waits for a natural break, and trash discards the notification."
      >
        <FormRow label="Active rules" value={String(rules.length)} icon="filter-outline" />
      </FormSection>
      {rules.map((rule, index) => (
        <RuleCard
          key={rule.id}
          rule={rule}
          first={index === 0}
          last={index === rules.length - 1}
          onMove={(direction) => {
            const target = index + direction;
            if (target < 0 || target >= rules.length) return;
            const next = [...rules];
            const other = next[target];
            if (!other) return;
            next[target] = rule;
            next[index] = other;
            update(next);
          }}
          onCycle={() => {
            const current = actionOrder.indexOf(rule.action);
            const action = actionOrder[(current + 1) % actionOrder.length] ?? "interrupt";
            update(rules.map((candidate) => candidate.id === rule.id ? { ...candidate, action } : candidate));
          }}
          onDelete={() => Alert.alert("Delete rule?", "Notifications that matched this rule will fall through to the next rule.", [
            { text: "Cancel", style: "cancel" },
            { text: "Delete", style: "destructive", onPress: () => update(rules.filter((candidate) => candidate.id !== rule.id)) },
          ])}
        />
      ))}
      {rules.length === 0 ? (
        <Text style={[styles.empty, { color: colors.secondaryText }]}>No rules yet. All notifications use the agent default.</Text>
      ) : null}
      <RuleComposer busy={save.isPending} onAdd={(rule) => update([...rules, rule])} />
      {save.error ? (
        <Text accessibilityRole="alert" style={{ color: colors.danger }}>
          {save.error instanceof Error ? save.error.message : "Could not save notification rules."}
        </Text>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  rule: { padding: 14 },
  ruleTop: { flexDirection: "row", gap: 12 },
  conditions: { flex: 1, gap: 4 },
  condition: { fontSize: 14, lineHeight: 19 },
  orderButtons: { justifyContent: "space-between", paddingVertical: 1 },
  ruleActions: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  badge: { borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
  badgeText: { fontSize: 13, fontWeight: "800", textTransform: "capitalize" },
  empty: { textAlign: "center", paddingVertical: 16, fontSize: 14 },
});
