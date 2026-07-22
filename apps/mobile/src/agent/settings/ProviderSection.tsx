import { useState } from "react";
import { Alert, StyleSheet, View } from "react-native";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import { Text } from "@/components/ui/Typography";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  completeClaudeOAuth,
  fetchManifest,
  fetchOpenRouterModels,
  fetchUsage,
  getProvider,
  provisionAgent,
  setContextWindow,
  setModel,
  signOutProvider,
  startClaudeOAuth,
  validateOpenRouterKey,
  type ProviderSelection,
} from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, FormRow, FormSection } from "@/components/ui/Form";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

type AuthKind = "claude" | "openrouter" | "zai" | "kimi";

export function ProviderSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const [authKind, setAuthKind] = useState<AuthKind>("claude");
  const provider = useQuery({
    queryKey: ["provider", name],
    queryFn: () => getProvider(api, name),
  });
  const manifest = useQuery({
    queryKey: ["manifest"],
    queryFn: () => fetchManifest(api),
  });
  const usage = useQuery({
    queryKey: ["usage", name],
    queryFn: () => fetchUsage(api, name),
  });
  const openRouterModels = useQuery({
    queryKey: ["openrouter-models"],
    queryFn: () => fetchOpenRouterModels(api),
    enabled: provider.data?.kind === "openrouter" || (provider.data?.kind === "none" && authKind === "openrouter"),
  });
  const [oauthSession, setOauthSession] = useState("");
  const [oauthCode, setOauthCode] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);

  const change = useMutation({
    mutationFn: async (operation: { type: "model" | "context"; value: string | number }) => {
      if (operation.type === "model") await setModel(api, name, String(operation.value));
      else await setContextWindow(api, name, Number(operation.value));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["provider", name] });
    },
  });

  if (provider.isLoading || manifest.isLoading) return <LoadingState label="Loading provider…" />;
  if (!provider.data || !manifest.data) {
    return <ErrorState message="Could not load provider settings." retry={() => { void provider.refetch(); void manifest.refetch(); }} />;
  }

  const providerKind = provider.data.kind === "none" ? authKind : provider.data.kind;
  const entry = manifest.data.providers[providerKind];
  const modelOptions =
    providerKind === "openrouter"
      ? (openRouterModels.data ?? []).map((model) => ({ label: model.label, value: model.slug }))
      : entry?.models === "live"
        ? []
        : (entry?.models ?? []).map((model) => ({ label: model.split("/").at(-1) ?? model, value: model }));

  const chooseModel = () => {
    const options = modelOptions.slice(0, 12).map((option) => ({
      text: option.label,
      onPress: () => change.mutate({ type: "model" as const, value: option.value }),
    }));
    Alert.alert("Choose model", undefined, [...options, { text: "Cancel", style: "cancel" }]);
  };

  const chooseContext = () => {
    const presets = entry?.context.presets ?? [];
    Alert.alert(
      "Context window",
      undefined,
      [
        ...presets.map((preset) => ({
          text: `${preset.label} (${preset.note})`,
          onPress: () => change.mutate({ type: "context" as const, value: preset.tokens }),
        })),
        { text: "Cancel", style: "cancel" as const },
      ],
    );
  };

  const connectClaude = async () => {
    setBusy(true);
    setAuthError("");
    try {
      if (!oauthSession) {
        const started = await startClaudeOAuth(api);
        setOauthSession(started.session_id);
        await WebBrowser.openBrowserAsync(started.auth_url, {
          presentationStyle: WebBrowser.WebBrowserPresentationStyle.PAGE_SHEET,
        });
      } else {
        const credentials = await completeClaudeOAuth(api, oauthSession, oauthCode.trim());
        const selection: ProviderSelection = {
          kind: "claude",
          credentials,
          model: provider.data?.model ?? entry?.default_model ?? undefined,
          maxContextTokens: provider.data?.max_context_tokens ?? entry?.context.default,
        };
        await provisionAgent(api, name, selection);
        await queryClient.invalidateQueries({ queryKey: ["provider", name] });
      }
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "Claude sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  const connectKeyProvider = async () => {
    if (providerKind === "claude") return;
    setBusy(true);
    setAuthError("");
    try {
      const key = providerKey.trim();
      if (providerKind === "openrouter") await validateOpenRouterKey(api, key);
      const selection: ProviderSelection = {
        kind: providerKind,
        key,
        model: provider.data?.model ?? entry?.default_model ?? modelOptions[0]?.value ?? "",
        maxContextTokens: provider.data?.max_context_tokens ?? entry?.context.default,
      };
      await provisionAgent(api, name, selection);
      await queryClient.invalidateQueries({ queryKey: ["provider", name] });
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "Provider sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  const needsAuthentication = provider.data.kind === "none" || !provider.data.authed;
  return (
    <>
      <FormSection title="Provider">
        <FormRow label="Provider" value={provider.data.kind} />
        <FormRow label="Authentication" value={provider.data.authed ? "connected" : "needed"} />
        <FormRow label="Plan" value={provider.data.plan ?? "not reported"} />
        <FormRow label="Model" value={provider.data.model ?? "not selected"} onPress={modelOptions.length > 0 ? chooseModel : undefined} />
        <FormRow label="Context" value={provider.data.max_context_tokens?.toLocaleString() ?? "default"} onPress={chooseContext} />
      </FormSection>

      {usage.data ? (
        <FormSection title="Usage">
          {usage.data.meters.map((meter) => (
            <View key={meter.label} style={styles.meter}>
              <View style={styles.meterLabels}>
                <Text style={[styles.meterTitle, { color: colors.text }]}>{meter.label}</Text>
                <Text style={[styles.meterValue, { color: colors.secondaryText }]}>{meter.used_pct === null ? "unknown" : `${Math.round(meter.used_pct)}%`}</Text>
              </View>
              <View style={[styles.track, { backgroundColor: colors.input }]}>
                <View style={[styles.fill, { backgroundColor: colors.accent, width: `${Math.min(meter.used_pct ?? 0, 100)}%` }]} />
              </View>
            </View>
          ))}
          {usage.data.credits ? (
            <FormRow label="Credits" value={`$${usage.data.credits.used?.toFixed(2) ?? "0.00"}${usage.data.credits.limit ? ` / $${usage.data.credits.limit.toFixed(2)}` : ""}`} />
          ) : null}
        </FormSection>
      ) : null}

      {needsAuthentication ? (
        <Card>
          <Text family="heading" style={[styles.authTitle, { color: colors.text }]}>Connect a provider</Text>
          {provider.data.kind === "none" ? (
            <View style={styles.kindButtons}>
              <Button variant={authKind === "claude" ? "primary" : "secondary"} onPress={() => setAuthKind("claude")}>Claude</Button>
              <Button variant={authKind === "zai" ? "primary" : "secondary"} onPress={() => setAuthKind("zai")}>Z.AI</Button>
              <Button variant={authKind === "kimi" ? "primary" : "secondary"} onPress={() => setAuthKind("kimi")}>Kimi</Button>
              <Button variant={authKind === "openrouter" ? "primary" : "secondary"} onPress={() => setAuthKind("openrouter")}>OpenRouter</Button>
            </View>
          ) : null}
          {providerKind === "claude" ? (
            <>
              {oauthSession ? (
                <>
                  <Field label="Authorization code" value={oauthCode} onChangeText={setOauthCode} autoCapitalize="none" autoCorrect={false} error={authError || undefined} />
                  <Button variant="secondary" icon="clipboard-outline" onPress={() => void Clipboard.getStringAsync().then(setOauthCode)}>Paste code</Button>
                </>
              ) : null}
              <Button loading={busy} disabled={Boolean(oauthSession && !oauthCode.trim())} onPress={() => void connectClaude()}>{oauthSession ? "Finish Claude sign-in" : "Open Claude sign-in"}</Button>
            </>
          ) : (
            <>
              <Field label={`${entry?.display ?? providerKind} API key`} value={providerKey} onChangeText={setProviderKey} secureTextEntry autoCapitalize="none" autoCorrect={false} error={authError || undefined} />
              <Button loading={busy} disabled={!providerKey.trim()} onPress={() => void connectKeyProvider()}>Connect {entry?.display ?? providerKind}</Button>
            </>
          )}
        </Card>
      ) : (
        <FormSection>
          <FormRow
            label="Sign out provider"
            icon="log-out-outline"
            destructive
            onPress={() => {
              Alert.alert("Sign out provider?", `${name} will stop responding until a provider is connected again.`, [
                { text: "Cancel", style: "cancel" },
                {
                  text: "Sign out",
                  style: "destructive",
                  onPress: () => void signOutProvider(api, name).then(() => queryClient.invalidateQueries({ queryKey: ["provider", name] })),
                },
              ]);
            }}
          />
        </FormSection>
      )}
      {change.error ? <Text style={{ color: colors.danger }}>{change.error instanceof Error ? change.error.message : "Could not update provider."}</Text> : null}
    </>
  );
}

const styles = StyleSheet.create({
  meter: { paddingHorizontal: 14, paddingVertical: 10, gap: 7 },
  meterLabels: { flexDirection: "row", justifyContent: "space-between" },
  meterTitle: { fontSize: 15, fontWeight: "600" },
  meterValue: { fontSize: 13 },
  track: { height: 6, borderRadius: 3, overflow: "hidden" },
  fill: { height: 6, borderRadius: 3 },
  authTitle: { fontSize: 19, fontWeight: "500" },
  kindButtons: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
});
