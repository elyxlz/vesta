import { Redirect } from "expo-router";
import { providerUsesOAuth } from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import {
  useOpenProviderStep,
  useProviderResource,
} from "@/agent/settings/provider-actions";
import {
  ClaudeSignIn,
  KeySignIn,
  OpenAISignIn,
} from "@/agent/settings/provider-auth-steps";
import { useProviderDraft } from "@/agent/settings/provider-draft";
import { ProviderStepScreen } from "@/agent/settings/provider-steps";
import { FormSectionSkeleton } from "@/components/ui/form-section-skeleton";

export default function ProviderSignInScreen() {
  const { name } = useAgent();
  const { resource } = useProviderResource();
  const { draft, update } = useProviderDraft();
  const openStep = useOpenProviderStep();
  const catalog = resource.data?.catalog;
  const kind = draft.kind;
  if (kind === null) {
    return (
      <Redirect
        href={{ pathname: "/agent/[name]/provider/choose", params: { name } }}
      />
    );
  }
  const entry = catalog?.providers[kind];
  const signedIn = (credentials: string) => {
    update({ credentials });
    openStep("model");
  };
  return (
    <ProviderStepScreen title={`Sign in to ${entry?.display ?? kind}`}>
      {!catalog ? (
        <FormSectionSkeleton rows={2} label="Loading sign-in" />
      ) : !providerUsesOAuth(kind, catalog) ? (
        <KeySignIn
          kind={kind}
          entry={entry}
          initialKey={draft.key}
          onKey={(key) => {
            update({ key });
            openStep("model");
          }}
        />
      ) : kind === "claude" ? (
        <ClaudeSignIn onCredentials={signedIn} />
      ) : (
        <OpenAISignIn onCredentials={signedIn} />
      )}
    </ProviderStepScreen>
  );
}
