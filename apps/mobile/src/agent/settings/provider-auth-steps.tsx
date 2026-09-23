import { useRef, useState } from "react";
import { StyleSheet, type TextInput } from "react-native";
import { useQuery } from "@tanstack/react-query";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import {
  completeClaudeOAuth,
  completeOpenAIOAuth,
  startClaudeOAuth,
  startOpenAIOAuth,
  validateOpenRouterKey,
  type ProviderCatalogEntry,
  type ProviderKind,
} from "@vesta/core";
import { StepAction, StepIntro } from "@/agent/settings/provider-steps";
import { useAgent } from "@/agent/AgentProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

// Resolves when the user closes the in-app browser sheet.
async function openSignIn(url: string) {
  await WebBrowser.openBrowserAsync(url, {
    presentationStyle: WebBrowser.WebBrowserPresentationStyle.PAGE_SHEET,
  });
}

// One OAuth session per visit to the step: leaving the step drops it, and a return starts fresh,
// so a code the user already pasted is never checked against a newer session.
function useOAuthSession<T>(kind: ProviderKind, start: () => Promise<T>) {
  const { name } = useAgent();
  return useQuery({
    queryKey: ["provider-oauth", name, kind],
    queryFn: start,
    gcTime: 0,
    staleTime: Infinity,
    retry: false,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  });
}

export function ClaudeSignIn({
  onCredentials,
}: {
  onCredentials: (credentials: string) => void;
}) {
  const { api } = useSession();
  const { name } = useAgent();
  const session = useOAuthSession("claude", () => startClaudeOAuth(api, name));
  const codeInput = useRef<TextInput>(null);
  const [code, setCode] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!session.data || code.trim() === "") return;
    setChecking(true);
    setError(null);
    try {
      onCredentials(
        await completeClaudeOAuth(
          api,
          name,
          session.data.session_id,
          code.trim(),
        ),
      );
    } catch (cause) {
      setError(errorText(cause, "The code did not work."));
    } finally {
      setChecking(false);
    }
  };

  return (
    <>
      <StepIntro kind="claude">
        Sign in to Claude, copy the code it shows, then paste it here.
      </StepIntro>
      <Button
        variant="secondary"
        icon="open-outline"
        disabled={!session.data}
        loading={session.isPending}
        onPress={() => {
          if (!session.data) return;
          void openSignIn(session.data.auth_url).then(() =>
            codeInput.current?.focus(),
          );
        }}
      >
        Open Claude sign-in
      </Button>
      <Field
        ref={codeInput}
        placeholder="Code"
        value={code}
        onChangeText={(next) => {
          setCode(next);
          setError(null);
        }}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="next"
        onSubmitEditing={() => void submit()}
        error={
          error ??
          (session.error
            ? errorText(session.error, "Could not start sign-in.")
            : undefined)
        }
      />
      <StepAction
        disabled={!session.data || code.trim() === ""}
        busy={checking}
        onPress={() => void submit()}
      >
        Next
      </StepAction>
    </>
  );
}

export function OpenAISignIn({
  onCredentials,
}: {
  onCredentials: (credentials: string) => void;
}) {
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const session = useOAuthSession("openai", () => startOpenAIOAuth(api, name));
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!session.data) return;
    setChecking(true);
    setError(null);
    try {
      onCredentials(
        await completeOpenAIOAuth(api, name, session.data.session_id),
      );
    } catch (cause) {
      setError(errorText(cause, "Sign-in is not complete yet."));
    } finally {
      setChecking(false);
    }
  };

  // The code goes to the clipboard on the way out, so the user only pastes it on the sign-in
  // page; closing the browser sheet checks the sign-in at once.
  const signIn = async (authUrl: string, userCode: string) => {
    await Clipboard.setStringAsync(userCode);
    await openSignIn(authUrl);
    await submit();
  };

  const failure =
    error ??
    (session.error
      ? errorText(session.error, "Could not start sign-in.")
      : null);
  return (
    <>
      <StepIntro kind="openai">
        Open ChatGPT sign-in and paste this one-time code. It is already on your
        clipboard.
      </StepIntro>
      <Card style={styles.codeCard}>
        <Text
          family="mono"
          selectable
          style={[styles.code, { color: colors.text }]}
        >
          {session.data?.user_code ?? "········"}
        </Text>
      </Card>
      <Button
        icon="open-outline"
        disabled={!session.data}
        loading={session.isPending || checking}
        onPress={() => {
          if (session.data)
            void signIn(session.data.auth_url, session.data.user_code);
        }}
      >
        Open ChatGPT sign-in
      </Button>
      {failure ? (
        <Text style={[styles.error, { color: colors.danger }]}>{failure}</Text>
      ) : null}
      <StepAction
        disabled={!session.data}
        busy={checking}
        onPress={() => void submit()}
      >
        Next
      </StepAction>
    </>
  );
}

export function KeySignIn({
  kind,
  entry,
  initialKey,
  onKey,
}: {
  kind: ProviderKind;
  entry: ProviderCatalogEntry | undefined;
  initialKey: string;
  onKey: (key: string) => void;
}) {
  const { api } = useSession();
  const { name } = useAgent();
  const [key, setKey] = useState(initialKey);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const display = entry?.display ?? kind;
  const keyName =
    entry?.auth_kind === "subscription_key" ? "subscription key" : "API key";

  const submit = async () => {
    const trimmed = key.trim();
    if (trimmed === "") return;
    setChecking(true);
    setError(null);
    try {
      if (kind === "openrouter")
        await validateOpenRouterKey(api, name, trimmed);
      onKey(trimmed);
    } catch (cause) {
      setError(errorText(cause, "The key did not work."));
    } finally {
      setChecking(false);
    }
  };

  return (
    <>
      <StepIntro kind={kind}>
        {`Paste your ${display} ${keyName}. It stays on your gateway.`}
      </StepIntro>
      <Field
        placeholder={`${display} ${keyName}`}
        value={key}
        onChangeText={(next) => {
          setKey(next);
          setError(null);
        }}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        autoFocus
        returnKeyType="next"
        onSubmitEditing={() => void submit()}
        error={error ?? undefined}
      />
      <StepAction
        disabled={key.trim() === ""}
        busy={checking}
        onPress={() => void submit()}
      >
        Next
      </StepAction>
    </>
  );
}

const styles = StyleSheet.create({
  codeCard: { alignItems: "center" },
  code: { fontSize: 26, fontWeight: "600", letterSpacing: 4 },
  error: { fontSize: 13, lineHeight: 18, textAlign: "center" },
});
