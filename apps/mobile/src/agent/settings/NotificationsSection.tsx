import { Alert, Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getNotificationInterruptRules,
  setNotificationInterruptRules,
} from "@vesta/core";
import type { FieldPredicate, NotificationInterruptRule } from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import { useToast } from "@/components/native-toast";
import { Card } from "@/components/ui/Card";
import { FormRow, FormSection } from "@/components/ui/Form";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { Quote, Text } from "@/components/ui/Typography";
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
            <Text
              key={condition}
              style={[styles.condition, { color: colors.secondaryText }]}
            >
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
            <Ionicons
              name="chevron-up"
              size={20}
              color={colors.secondaryText}
            />
          </Pressable>
          <Pressable
            accessibilityLabel="Move rule later"
            disabled={last}
            onPress={() => onMove(1)}
            hitSlop={8}
            style={{ opacity: last ? 0.25 : 1 }}
          >
            <Ionicons
              name="chevron-down"
              size={20}
              color={colors.secondaryText}
            />
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
          <Text style={[styles.badgeText, { color: actionColor }]}>
            {rule.action}
          </Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Delete rule"
          onPress={onDelete}
          hitSlop={8}
        >
          <Ionicons name="trash-outline" size={19} color={colors.danger} />
        </Pressable>
      </View>
    </Card>
  );
}

export function NotificationsSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { showError } = useToast();
  const { colors } = usePreferences();
  const query = useQuery({
    queryKey: ["notification-rules", name],
    queryFn: () => getNotificationInterruptRules(api, name),
  });
  const save = useMutation({
    mutationFn: (rules: NotificationInterruptRule[]) =>
      setNotificationInterruptRules(api, name, rules),
    onMutate: async (rules) => {
      await queryClient.cancelQueries({
        queryKey: ["notification-rules", name],
      });
      const previous = queryClient.getQueryData<NotificationInterruptRule[]>([
        "notification-rules",
        name,
      ]);
      queryClient.setQueryData(["notification-rules", name], rules);
      return { previous };
    },
    onError: (error, _rules, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          ["notification-rules", name],
          context.previous,
        );
      }
      showError(error, "Could not save notification rules");
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: ["notification-rules", name],
      });
    },
  });

  if (query.isLoading)
    return <LoadingState label="Loading notification rules…" />;
  if (!query.data) {
    return (
      <ErrorState
        message="Notification rules are unavailable."
        retry={() => void query.refetch()}
      />
    );
  }

  const rules = query.data;
  const update = (next: NotificationInterruptRule[]) => save.mutate(next);
  return (
    <>
      <Card style={styles.hint}>
        <Text style={[styles.hintTitle, { color: colors.text }]}>
          {rules.length === 0 ? "No rules yet" : "Add a rule"}
        </Text>
        <Text style={[styles.hintText, { color: colors.secondaryText }]}>
          Just ask {name} in chat, for example{" "}
          <Quote>“don’t let Twitter interrupt you”</Quote> or{" "}
          <Quote>“snooze the family group chat”</Quote>.
        </Text>
      </Card>
      <FormSection
        title="Priority rules"
        footer="Rules are checked from top to bottom. Interrupt delivers now, snooze waits for a natural break, and trash discards the notification."
      >
        <FormRow
          label="Active rules"
          value={String(rules.length)}
          icon="filter-outline"
        />
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
            const action =
              actionOrder[(current + 1) % actionOrder.length] ?? "interrupt";
            update(
              rules.map((candidate) =>
                candidate.id === rule.id ? { ...candidate, action } : candidate,
              ),
            );
          }}
          onDelete={() =>
            Alert.alert(
              "Delete rule?",
              "Notifications that matched this rule will fall through to the next rule.",
              [
                { text: "Cancel", style: "cancel" },
                {
                  text: "Delete",
                  style: "destructive",
                  onPress: () =>
                    update(
                      rules.filter((candidate) => candidate.id !== rule.id),
                    ),
                },
              ],
            )
          }
        />
      ))}
    </>
  );
}

const styles = StyleSheet.create({
  rule: { padding: 14 },
  ruleTop: { flexDirection: "row", gap: 12 },
  conditions: { flex: 1, gap: 4 },
  condition: { fontSize: 14, lineHeight: 19 },
  orderButtons: { justifyContent: "space-between", paddingVertical: 1 },
  ruleActions: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  badge: {
    borderRadius: 999,
    borderCurve: "continuous",
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  badgeText: { fontSize: 13, fontWeight: "800", textTransform: "capitalize" },
  hint: { padding: 14, gap: 4 },
  hintTitle: { fontSize: 15, fontWeight: "600" },
  hintText: { fontSize: 14, lineHeight: 19 },
});
