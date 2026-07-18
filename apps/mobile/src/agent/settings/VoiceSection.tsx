import { useState } from "react";
import { Alert, StyleSheet, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchVoiceStatus,
  setVoiceEnabled,
  setVoiceSetting,
} from "@/api/endpoints";
import type { SettingDef, VoiceStatus } from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

type VoiceDomain = "stt" | "tts";

function settingValue(setting: SettingDef): string {
  if (typeof setting.value === "string") return setting.value;
  if (typeof setting.value === "number") return String(setting.value);
  if (typeof setting.value === "boolean") return setting.value ? "on" : "off";
  return "default";
}

function VoiceSetting({
  setting,
  domain,
  onChange,
  busy,
}: {
  setting: SettingDef;
  domain: VoiceDomain;
  onChange: (domain: VoiceDomain, key: string, value: unknown) => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState(settingValue(setting));

  if (setting.type === "bool") {
    return (
      <SwitchRow
        label={setting.label}
        detail={setting.description}
        value={Boolean(setting.value)}
        onValueChange={(value) => onChange(domain, setting.key, value)}
      />
    );
  }

  if (setting.type === "select") {
    const choose = () => {
      const choices = (setting.options ?? []).map((option) => ({
        text: option.label,
        onPress: () => onChange(domain, setting.key, option.value),
      }));
      Alert.alert(setting.label, setting.description, [
        ...choices,
        { text: "Cancel", style: "cancel" },
      ]);
    };
    return (
      <FormRow
        label={setting.label}
        detail={setting.description}
        value={settingValue(setting)}
        onPress={choose}
      />
    );
  }

  return (
    <View style={styles.numberSetting}>
      <Field
        label={setting.label}
        description={setting.description}
        value={draft}
        onChangeText={setDraft}
        keyboardType="decimal-pad"
      />
      <Button
        variant="secondary"
        disabled={busy || !Number.isFinite(Number(draft))}
        onPress={() => onChange(domain, setting.key, Number(draft))}
      >
        Apply
      </Button>
    </View>
  );
}

function DomainCard({
  domain,
  status,
  onToggle,
  onSetting,
  busy,
}: {
  domain: VoiceDomain;
  status: VoiceStatus;
  onToggle: (domain: VoiceDomain, value: boolean) => void;
  onSetting: (domain: VoiceDomain, key: string, value: unknown) => void;
  busy: boolean;
}) {
  const { colors } = usePreferences();
  const title = domain === "stt" ? "Speech to text" : "Text to speech";
  return (
    <Card>
      <View style={styles.domainHeader}>
        <View style={styles.domainTitle}>
          <Text family="heading" style={[styles.title, { color: colors.text }]}>{title}</Text>
          <Text style={[styles.provider, { color: colors.secondaryText }]}>
            {status.provider ?? "not configured"}
          </Text>
        </View>
      </View>
      <SwitchRow
        label={status.configured ? "Enabled" : "Needs configuration"}
        detail={
          status.configured
            ? domain === "stt"
              ? "Use live transcription in chat."
              : "Speak new replies when available."
            : "Ask the agent to configure this voice service."
        }
        value={status.configured && status.enabled !== false}
        disabled={!status.configured || busy}
        onValueChange={(value) => onToggle(domain, value)}
      />
      {status.configured && status.enabled !== false
        ? (status.settings ?? []).map((setting) => (
            <VoiceSetting
              key={setting.key}
              setting={setting}
              domain={domain}
              onChange={onSetting}
              busy={busy}
            />
          ))
        : null}
    </Card>
  );
}

export function VoiceSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const status = useQuery({
    queryKey: ["voice", name],
    queryFn: async () => {
      const [stt, tts] = await Promise.all([
        fetchVoiceStatus(api, name, "stt"),
        fetchVoiceStatus(api, name, "tts"),
      ]);
      return { stt, tts };
    },
  });
  const change = useMutation({
    mutationFn: async (
      operation:
        | { type: "enabled"; domain: VoiceDomain; value: boolean }
        | { type: "setting"; domain: VoiceDomain; key: string; value: unknown },
    ) => {
      if (operation.type === "enabled") {
        await setVoiceEnabled(api, name, operation.domain, operation.value);
      } else {
        await setVoiceSetting(
          api,
          name,
          operation.domain,
          operation.key,
          operation.value,
        );
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["voice", name] });
    },
  });

  if (status.isLoading) return <LoadingState label="Loading voice services…" />;
  if (!status.data) {
    return (
      <ErrorState
        message={status.error instanceof Error ? status.error.message : "Voice settings are unavailable."}
        retry={() => void status.refetch()}
      />
    );
  }

  return (
    <>
      <FormSection
        title="Live voice"
        footer="Voice processing uses the services configured by this agent. Microphone access is requested only when you start listening."
      >
        <FormRow
          label="Conversation mode"
          detail="Tap the microphone in Chat to stream speech and send completed turns."
          icon="mic-outline"
        />
      </FormSection>
      <DomainCard
        domain="stt"
        status={status.data.stt}
        busy={change.isPending}
        onToggle={(domain, value) => change.mutate({ type: "enabled", domain, value })}
        onSetting={(domain, key, value) => change.mutate({ type: "setting", domain, key, value })}
      />
      <DomainCard
        domain="tts"
        status={status.data.tts}
        busy={change.isPending}
        onToggle={(domain, value) => change.mutate({ type: "enabled", domain, value })}
        onSetting={(domain, key, value) => change.mutate({ type: "setting", domain, key, value })}
      />
      {change.error ? (
        <Text accessibilityRole="alert" style={{ color: colors.danger }}>
          {change.error instanceof Error ? change.error.message : "Could not save the voice setting."}
        </Text>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  domainHeader: { flexDirection: "row", alignItems: "center" },
  domainTitle: { flex: 1 },
  title: { fontSize: 19, fontWeight: "500" },
  provider: { fontSize: 13, marginTop: 2 },
  numberSetting: { gap: 8 },
});
