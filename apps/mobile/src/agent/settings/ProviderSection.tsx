import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { resolveProviderIdentity, signOutProvider } from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import {
  useOpenProviderStep,
  useProviderResource,
} from "@/agent/settings/provider-actions";
import { useProviderDraft } from "@/agent/settings/provider-draft";
import {
  contextLabel,
  contextPolicyToOffer,
} from "@/agent/settings/provider-model";
import { ProviderChoiceList } from "@/agent/settings/provider-steps";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useToast } from "@/components/native-toast";
import { ProviderLogo } from "@/components/ProviderLogo";
import { FormRow, FormSection } from "@/components/ui/Form";
import { FormSectionSkeleton } from "@/components/ui/form-section-skeleton";
import { ErrorState } from "@/components/ui/States";
import { useSession } from "@/session/SessionProvider";

// An agent that needs a provider opens straight on the provider choice. A signed-in agent shows
// what it runs on, and each row pushes the one step that changes it.
export function ProviderSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { showError } = useToast();
  const { resource, signedInKind } = useProviderResource();
  const { start } = useProviderDraft();
  const openStep = useOpenProviderStep();
  const [confirmingSignOut, setConfirmingSignOut] = useState(false);
  const signOut = useMutation({
    mutationFn: () => signOutProvider(api, name),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["provider", name] }),
    onError: (error) => showError(error, "Could not sign out"),
  });

  if (resource.isLoading) {
    return (
      <FormSectionSkeleton title="Provider" rows={3} label="Loading provider" />
    );
  }
  const provider = resource.data?.provider;
  const catalog = resource.data?.catalog;
  if (!provider || !catalog) {
    return (
      <ErrorState
        message="Could not load the provider."
        retry={() => void resource.refetch()}
      />
    );
  }

  if (signedInKind === null) {
    return (
      <ProviderChoiceList
        catalog={catalog}
        onPick={(kind) => {
          start(kind);
          openStep("sign-in");
        }}
      />
    );
  }

  const entry = catalog.providers[signedInKind];
  const policy = contextPolicyToOffer(
    signedInKind,
    entry,
    provider.model ?? entry?.default_model ?? "",
  );
  const identity = resolveProviderIdentity(provider, catalog);
  return (
    <View style={styles.summary}>
      <FormSection>
        <FormRow
          leading={<ProviderLogo kind={signedInKind} size={24} />}
          label="Provider"
          value={identity?.providerName ?? signedInKind}
          onPress={() => openStep("choose")}
        />
        <FormRow
          label="Model"
          value={identity?.modelName ?? "Default"}
          onPress={() => openStep("model", true)}
        />
        {policy ? (
          <FormRow
            label="Context window"
            value={contextLabel(
              provider.max_context_tokens ?? policy.default,
              policy,
            )}
            onPress={() => openStep("context", true)}
          />
        ) : null}
      </FormSection>
      <FormSection>
        <FormRow
          label="Sign out"
          icon="log-out-outline"
          destructive
          onPress={() => setConfirmingSignOut(true)}
        />
      </FormSection>
      <ConfirmDialog
        visible={confirmingSignOut}
        title="Sign out of the provider?"
        message={`${name} stops responding until a provider is connected again.`}
        confirmLabel="Sign out"
        destructive
        onConfirm={() => {
          setConfirmingSignOut(false);
          signOut.mutate();
        }}
        onDismiss={() => setConfirmingSignOut(false)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  summary: { gap: 24 },
});
