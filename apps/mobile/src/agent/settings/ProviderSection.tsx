import { useState } from "react";
import {
  completeClaudeOAuth,
  completeOpenAIOAuth,
  fetchAgentClaudeModels,
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
  type Account,
  type ProviderKind,
  type ProviderSelection,
} from "@vesta/core";
import { Alert, StyleSheet, View } from "react-native";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import { Text } from "@/components/ui/Typography";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAgent } from "@/agent/AgentProvider";
import { useAwaitedRoundTrip } from "@/agent/use-awaited-round-trip";
import {
  buildModelOptions,
  resolveProviderKind,
  sortAdvertisedProviders,
} from "@/agent/settings/provider-model";
import { useToast } from "@/components/native-toast";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, FormRow, FormSection } from "@/components/ui/Form";
import { FormSectionSkeleton } from "@/components/ui/form-section-skeleton";
import { ErrorState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

type KeyProviderKind = Extract<ProviderSelection, { key: string }>["kind"];

function formatMemberSince(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
  });
}

function AccountSection({ account }: { account: Account }) {
  const rows = [
    { label: "Name", value: account.name },
    { label: "Email", value: account.email },
    { label: "Plan", value: account.plan },
    { label: "Organization", value: account.organization },
    {
      label: "Member since",
      value: account.created_at ? formatMemberSince(account.created_at) : null,
    },
  ].filter(
    (row): row is { label: string; value: string } => row.value !== null,
  );

  if (rows.length === 0) return null;

  return (
    <FormSection title="Account">
      {rows.map((row) => (
        <FormRow key={row.label} label={row.label} value={row.value} />
      ))}
    </FormSection>
  );
}

function isKeyProviderKind(kind: ProviderKind): kind is KeyProviderKind {
  return kind === "openrouter" || kind === "zai" || kind === "kimi";
}

export function ProviderSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name, agent } = useAgent();
  const { showError } = useToast();
  const { colors } = usePreferences();
  const [authKind, setAuthKind] = useState<ProviderKind>("claude");
  const providerResource = useQuery({
    queryKey: ["provider", name],
    queryFn: () => getProvider(api, name),
  });
  const provider = providerResource.data?.provider;
  const catalog = providerResource.data?.catalog;
  const usage = useQuery({
    queryKey: ["usage", name],
    queryFn: () => fetchUsage(api, name),
  });
  const openRouterModels = useQuery({
    queryKey: ["openrouter-models", name],
    queryFn: () => fetchOpenRouterModels(api, name),
    enabled:
      provider?.kind === "openrouter" ||
      (provider?.kind === "none" && authKind === "openrouter"),
  });
  // Enabled only once signed in: the agent lists models with its stored OAuth token,
  // so before sign-in (kind "none") the endpoint can only 409.
  const claudeModels = useQuery({
    queryKey: ["claude-models", name],
    queryFn: () => fetchAgentClaudeModels(api, name),
    enabled: provider?.kind === "claude",
    // The catalog changes on the order of months; don't re-run the two-hop
    // Anthropic call on every settings visit.
    staleTime: 60 * 60 * 1000,
  });
  const [oauthSession, setOauthSession] = useState("");
  const [oauthCode, setOauthCode] = useState("");
  const [openAIUserCode, setOpenAIUserCode] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [requestBusy, setBusy] = useState(false);
  // Provisioning ends in an agent restart; the section stays busy until the roster shows it back.
  const restart = useAwaitedRoundTrip(agent?.status !== "alive");
  const busy = requestBusy || restart.busy;

  const selectAuthKind = (kind: ProviderKind) => {
    setAuthKind(kind);
    setOauthSession("");
    setOauthCode("");
    setOpenAIUserCode("");
    setProviderKey("");
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
    onError: (error) => showError(error, "Could not update provider"),
  });

  if (providerResource.isLoading) {
    return (
      <>
        <FormSectionSkeleton
          title="Provider"
          rows={5}
          label="Loading provider"
        />
        <FormSectionSkeleton title="Account" rows={3} label="Loading account" />
        <FormSectionSkeleton title="Usage" rows={2} label="Loading usage" />
      </>
    );
  }
  if (!provider || !catalog) {
    return (
      <ErrorState
        message="Could not load provider settings."
        retry={() => {
          void providerResource.refetch();
        }}
      />
    );
  }

  const providerKind = resolveProviderKind(provider.kind, authKind);
  const entry = catalog.providers[providerKind];
  const selectedModel = provider.model ?? entry?.default_model ?? "";
  const context = entry?.context_by_model?.[selectedModel] ?? entry?.context;
  const advertisedProviders = sortAdvertisedProviders(catalog.providers);
  const modelOptions = buildModelOptions(
    providerKind,
    entry,
    openRouterModels.data,
    claudeModels.data,
  );

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

  // One OAuth flow for both browser-based providers: the first press starts a session and opens
  // the browser (OpenAI also surfaces its one-time code), the second completes and provisions.
  const connectOAuth = async (kind: "claude" | "openai") => {
    setBusy(true);
    try {
      if (!oauthSession) {
        let started: { auth_url: string; session_id: string };
        if (kind === "claude") {
          started = await startClaudeOAuth(api, name);
        } else {
          const openAIStart = await startOpenAIOAuth(api, name);
          setOpenAIUserCode(openAIStart.user_code);
          started = openAIStart;
        }
        setOauthSession(started.session_id);
        await WebBrowser.openBrowserAsync(started.auth_url, {
          presentationStyle: WebBrowser.WebBrowserPresentationStyle.PAGE_SHEET,
        });
      } else {
        const maxContextTokens =
          provider?.max_context_tokens ?? context?.default;
        const selection: ProviderSelection =
          kind === "claude"
            ? {
                kind,
                credentials: await completeClaudeOAuth(
                  api,
                  name,
                  oauthSession,
                  oauthCode.trim(),
                ),
                model: provider?.model ?? entry?.default_model ?? undefined,
                maxContextTokens,
              }
            : {
                kind,
                credentials: await completeOpenAIOAuth(api, name, oauthSession),
                model: selectedModel,
                maxContextTokens,
              };
        await provisionAgent(api, name, selection);
        restart.start();
        await queryClient.invalidateQueries({ queryKey: ["provider", name] });
      }
    } catch (cause) {
      showError(
        cause,
        kind === "claude" ? "Claude sign-in failed" : "OpenAI sign-in failed",
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
    try {
      const key = providerKey.trim();
      if (providerKind === "openrouter")
        await validateOpenRouterKey(api, name, key);
      const defaultContext = provider?.max_context_tokens ?? context?.default;
      const selection: ProviderSelection = {
        kind: providerKind,
        key,
        model: selectedModel || modelOptions[0]?.value || "",
        ...(defaultContext ? { maxContextTokens: defaultContext } : {}),
      };
      await provisionAgent(api, name, selection);
      restart.start();
      await queryClient.invalidateQueries({ queryKey: ["provider", name] });
    } catch (cause) {
      showError(cause, "Provider sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  const needsAuthentication = provider.kind === "none" || !provider.authed;
  return (
    <>
      <FormSection title="Provider">
        <FormRow label="Provider" value={provider.kind} />
        <FormRow
          label="Authentication"
          value={provider.authed ? "connected" : "needed"}
        />
        <FormRow label="Plan" value={provider.plan ?? "not reported"} />
        <FormRow
          label="Model"
          value={provider.model ?? "not selected"}
          onPress={modelOptions.length > 0 ? chooseModel : undefined}
        />
        <FormRow
          label="Context"
          value={
            provider.max_context_tokens?.toLocaleString() ??
            (providerKind === "openrouter" ? "model limit" : "default")
          }
          onPress={
            (context?.presets.length ?? 0) > 0 ? chooseContext : undefined
          }
        />
      </FormSection>

      {usage.isPending ? (
        <>
          <FormSectionSkeleton
            title="Account"
            rows={3}
            label="Loading account"
          />
          <FormSectionSkeleton title="Usage" rows={2} label="Loading usage" />
        </>
      ) : null}

      {usage.data?.account ? (
        <AccountSection account={usage.data.account} />
      ) : null}

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
          {provider.kind === "none" ? (
            <View style={styles.kindButtons}>
              {advertisedProviders.map((kind) => (
                <Button
                  key={kind}
                  variant={authKind === kind ? "primary" : "secondary"}
                  onPress={() => selectAuthKind(kind)}
                >
                  {catalog.providers[kind]?.display ?? kind}
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
                onPress={() => void connectOAuth("claude")}
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
              <Button
                loading={busy}
                onPress={() => void connectOAuth("openai")}
              >
                {oauthSession
                  ? "Finish OpenAI sign-in"
                  : "Open ChatGPT sign-in"}
              </Button>
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
                      void signOutProvider(api, name)
                        .then(() =>
                          queryClient.invalidateQueries({
                            queryKey: ["provider", name],
                          }),
                        )
                        .catch((error: unknown) =>
                          showError(error, "Could not sign out provider"),
                        ),
                  },
                ],
              );
            }}
          />
        </FormSection>
      )}
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
