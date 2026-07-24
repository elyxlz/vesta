import { useState } from "react";
import type { ProviderKind } from "@vesta/core";
import { Alert, StyleSheet, View } from "react-native";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import { Text } from "@/components/ui/Typography";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  completeClaudeOAuth,
  completeOpenAIOAuth,
  fetchManifest,
  fetchOpenRouterModels,
  fetchUsage,
  getProvider,
  provisionAgent,
  setContextWindow,
  setModel,
  signOutProvider,
  startClaudeOAuth,
  startOpenAIOAuth,
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

type KeyProviderKind = Extract<ProviderSelection, { key: string }>["kind"];

function isKeyProviderKind(kind: ProviderKind): kind is KeyProviderKind {
  return kind === "openrouter" || kind === "zai" || kind === "kimi";
}

export function ProviderSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const [authKind, setAuthKind] = useState<ProviderKind>("claude");
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
    enabled:
      provider.data?.kind === "openrouter" ||
      (provider.data?.kind === "none" && authKind === "openrouter"),
  });
  const [oauthSession, setOauthSession] = useState("");
  const [oauthCode, setOauthCode] = useState("");
  const [openAIUserCode, setOpenAIUserCode] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);

  const selectAuthKind = (kind: ProviderKind) => {
    setAuthKind(kind);
    setOauthSession("");
    setOauthCode("");
    setOpenAIUserCode("");
    setProviderKey("");
    setAuthError("");
  };

  const change = useMutation({
    mutationFn: async (operation: {
      type: "model" | "context";
      value: string | number;
    }) => {
      if (operation.type === "model")
        await setModel(api, name, String(operation.value));
      else await setContextWindow(api, name, Number(operation.value));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["provider", name] });
    },
  });

  if (provider.isLoading || manifest.isLoading)
    return <LoadingState label="Loading provider…" />;
  if (!provider.data || !manifest.data) {
    return (
      <ErrorState
        message="Could not load provider settings."
        retry={() => {
          void provider.refetch();
          void manifest.refetch();
        }}
      />
    );
  }

  const providerKind =
    provider.data.kind === "none" ? authKind : provider.data.kind;
  const entry = manifest.data.providers[providerKind];
  const selectedModel = provider.data.model ?? entry?.default_model ?? "";
  const context = entry?.context_by_model?.[selectedModel] ?? entry?.context;
  const advertisedProviders = (
    Object.keys(manifest.data.providers) as ProviderKind[]
  ).sort(
    (left, right) =>
      (manifest.data.providers[left]?.order ?? Number.MAX_SAFE_INTEGER) -
      (manifest.data.providers[right]?.order ?? Number.MAX_SAFE_INTEGER),
  );
  const modelOptions =
    providerKind === "openrouter"
      ? (openRouterModels.data ?? []).map((model) => ({
          label: model.label,
          value: model.slug,
        }))
      : entry?.models === "live"
        ? []
        : (entry?.models ?? []).map((model) => ({
            label: model.split("/").at(-1) ?? model,
            value: model,
          }));

  const chooseModel = () => {
    const options = modelOptions.slice(0, 12).map((option) => ({
      text: option.label,
      onPress: () =>
        change.mutate({ type: "model" as const, value: option.value }),
    }));
    Alert.alert("Choose model", undefined, [
      ...options,
      { text: "Cancel", style: "cancel" },
    ]);
  };

  const chooseContext = () => {
    const presets = context?.presets ?? [];
    Alert.alert("Context window", undefined, [
      ...presets.map((preset) => ({
        text: `${preset.label} (${preset.note})`,
        onPress: () =>
          change.mutate({ type: "context" as const, value: preset.tokens }),
      })),
      { text: "Cancel", style: "cancel" as const },
    ]);
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
        const credentials = await completeClaudeOAuth(
          api,
          oauthSession,
          oauthCode.trim(),
        );
        const selection: ProviderSelection = {
          kind: "claude",
          credentials,
          model: provider.data?.model ?? entry?.default_model ?? undefined,
          maxContextTokens:
            provider.data?.max_context_tokens ?? context?.default,
        };
        await provisionAgent(api, name, selection);
        await queryClient.invalidateQueries({ queryKey: ["provider", name] });
      }
    } catch (cause) {
      setAuthError(
        cause instanceof Error ? cause.message : "Claude sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const connectOpenAI = async () => {
    setBusy(true);
    setAuthError("");
    try {
      if (!oauthSession) {
        const started = await startOpenAIOAuth(api);
        setOauthSession(started.session_id);
        setOpenAIUserCode(started.user_code);
        await WebBrowser.openBrowserAsync(started.auth_url, {
          presentationStyle: WebBrowser.WebBrowserPresentationStyle.PAGE_SHEET,
        });
      } else {
        const credentials = await completeOpenAIOAuth(api, oauthSession);
        const selection: ProviderSelection = {
          kind: "openai",
          credentials,
          model: selectedModel,
          maxContextTokens:
            provider.data?.max_context_tokens ?? context?.default,
        };
        await provisionAgent(api, name, selection);
        await queryClient.invalidateQueries({ queryKey: ["provider", name] });
      }
    } catch (cause) {
      setAuthError(
        cause instanceof Error ? cause.message : "OpenAI sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const connectKeyProvider = async () => {
    if (
      entry?.auth_kind !== "api_key" &&
      entry?.auth_kind !== "subscription_key"
    )
      return;
    if (!isKeyProviderKind(providerKind)) return;
    setBusy(true);
    setAuthError("");
    try {
      const key = providerKey.trim();
      if (providerKind === "openrouter") await validateOpenRouterKey(api, key);
      const defaultContext =
        provider.data?.max_context_tokens ?? context?.default;
      const selection: ProviderSelection = {
        kind: providerKind,
        key,
        model: selectedModel || modelOptions[0]?.value || "",
        ...(defaultContext ? { maxContextTokens: defaultContext } : {}),
      };
      await provisionAgent(api, name, selection);
      await queryClient.invalidateQueries({ queryKey: ["provider", name] });
    } catch (cause) {
      setAuthError(
        cause instanceof Error ? cause.message : "Provider sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const needsAuthentication =
    provider.data.kind === "none" || !provider.data.authed;
  return (
    <>
      <FormSection title="Provider">
        <FormRow label="Provider" value={provider.data.kind} />
        <FormRow
          label="Authentication"
          value={provider.data.authed ? "connected" : "needed"}
        />
        <FormRow label="Plan" value={provider.data.plan ?? "not reported"} />
        <FormRow
          label="Model"
          value={provider.data.model ?? "not selected"}
          onPress={modelOptions.length > 0 ? chooseModel : undefined}
        />
        <FormRow
          label="Context"
          value={
            provider.data.max_context_tokens?.toLocaleString() ??
            (providerKind === "openrouter" ? "model limit" : "default")
          }
          onPress={
            (context?.presets.length ?? 0) > 0 ? chooseContext : undefined
          }
        />
      </FormSection>

      {usage.data ? (
        <FormSection title="Usage">
          {usage.data.meters.map((meter) => (
            <View key={meter.label} style={styles.meter}>
              <View style={styles.meterLabels}>
                <Text style={[styles.meterTitle, { color: colors.text }]}>
                  {meter.label}
                </Text>
                <Text
                  style={[styles.meterValue, { color: colors.secondaryText }]}
                >
                  {meter.used_pct === null
                    ? "unknown"
                    : `${Math.round(meter.used_pct)}%`}
                </Text>
              </View>
              <View style={[styles.track, { backgroundColor: colors.input }]}>
                <View
                  style={[
                    styles.fill,
                    {
                      backgroundColor: colors.accent,
                      width: `${Math.min(meter.used_pct ?? 0, 100)}%`,
                    },
                  ]}
                />
              </View>
            </View>
          ))}
          {usage.data.credits ? (
            <FormRow
              label="Credits"
              value={`$${usage.data.credits.used?.toFixed(2) ?? "0.00"}${usage.data.credits.limit ? ` / $${usage.data.credits.limit.toFixed(2)}` : ""}`}
            />
          ) : null}
        </FormSection>
      ) : null}

      {needsAuthentication ? (
        <Card>
          <Text
            family="heading"
            style={[styles.authTitle, { color: colors.text }]}
          >
            Connect a provider
          </Text>
          {provider.data.kind === "none" ? (
            <View style={styles.kindButtons}>
              {advertisedProviders.map((kind) => (
                <Button
                  key={kind}
                  variant={authKind === kind ? "primary" : "secondary"}
                  onPress={() => selectAuthKind(kind)}
                >
                  {manifest.data.providers[kind]?.display ?? kind}
                </Button>
              ))}
            </View>
          ) : null}
          {providerKind === "claude" ? (
            <>
              {oauthSession ? (
                <>
                  <Field
                    label="Authorization code"
                    value={oauthCode}
                    onChangeText={setOauthCode}
                    autoCapitalize="none"
                    autoCorrect={false}
                    error={authError || undefined}
                  />
                  <Button
                    variant="secondary"
                    icon="clipboard-outline"
                    onPress={() =>
                      void Clipboard.getStringAsync().then(setOauthCode)
                    }
                  >
                    Paste code
                  </Button>
                </>
              ) : null}
              <Button
                loading={busy}
                disabled={Boolean(oauthSession && !oauthCode.trim())}
                onPress={() => void connectClaude()}
              >
                {oauthSession ? "Finish Claude sign-in" : "Open Claude sign-in"}
              </Button>
            </>
          ) : providerKind === "openai" ? (
            <>
              {openAIUserCode ? (
                <>
                  <FormRow label="One-time code" value={openAIUserCode} />
                  <Button
                    variant="secondary"
                    icon="copy-outline"
                    onPress={() =>
                      void Clipboard.setStringAsync(openAIUserCode)
                    }
                  >
                    Copy code
                  </Button>
                </>
              ) : null}
              <Button loading={busy} onPress={() => void connectOpenAI()}>
                {oauthSession
                  ? "Finish OpenAI sign-in"
                  : "Open ChatGPT sign-in"}
              </Button>
              {authError ? (
                <Text style={{ color: colors.danger }}>{authError}</Text>
              ) : null}
            </>
          ) : (
            <>
              <Field
                label={`${entry?.display ?? providerKind} ${providerKind === "openrouter" ? "API" : "subscription"} key`}
                value={providerKey}
                onChangeText={setProviderKey}
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
                error={authError || undefined}
              />
              <Button
                loading={busy}
                disabled={!providerKey.trim()}
                onPress={() => void connectKeyProvider()}
              >
                Connect {entry?.display ?? providerKind}
              </Button>
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
              Alert.alert(
                "Sign out provider?",
                `${name} will stop responding until a provider is connected again.`,
                [
                  { text: "Cancel", style: "cancel" },
                  {
                    text: "Sign out",
                    style: "destructive",
                    onPress: () =>
                      void signOutProvider(api, name).then(() =>
                        queryClient.invalidateQueries({
                          queryKey: ["provider", name],
                        }),
                      ),
                  },
                ],
              );
            }}
          />
        </FormSection>
      )}
      {change.error ? (
        <Text style={{ color: colors.danger }}>
          {change.error instanceof Error
            ? change.error.message
            : "Could not update provider."}
        </Text>
      ) : null}
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
