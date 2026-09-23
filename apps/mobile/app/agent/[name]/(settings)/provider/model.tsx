import { Redirect, useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import {
  canonicalClaudeModel,
  fetchAgentClaudeModels,
  fetchClaudeModelsWithCredentials,
  fetchOpenRouterModels,
  modelStepInitialModel,
} from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import {
  useFinishSetup,
  useOpenProviderStep,
  useProviderChange,
  useProviderResource,
} from "@/agent/settings/provider-actions";
import { useProviderDraft } from "@/agent/settings/provider-draft";
import {
  buildModelOptions,
  contextPolicyToOffer,
} from "@/agent/settings/provider-model";
import { ModelList, ProviderStepScreen } from "@/agent/settings/provider-steps";
import { FormSectionSkeleton } from "@/components/ui/form-section-skeleton";
import { useSession } from "@/session/SessionProvider";

// Setup picks the model into the draft and moves on; `change` applies it to the signed-in agent.
export default function ProviderModelScreen() {
  const { api } = useSession();
  const { name } = useAgent();
  const change = useLocalSearchParams<{ change?: string }>().change === "1";
  const { resource, signedInKind } = useProviderResource();
  const { draft, update } = useProviderDraft();
  const openStep = useOpenProviderStep();
  const { finish, provision } = useFinishSetup();
  const apply = useProviderChange();
  const kind = change ? signedInKind : draft.kind;
  const openRouterModels = useQuery({
    queryKey: ["openrouter-models", name],
    queryFn: () => fetchOpenRouterModels(api, name),
    enabled: kind === "openrouter",
  });
  // A signed-in agent lists Claude models with its own token; a setup lends it the fresh one.
  const claudeModels = useQuery({
    queryKey: ["claude-models", name, change ? null : draft.credentials],
    queryFn: () =>
      change
        ? fetchAgentClaudeModels(api, name)
        : fetchClaudeModelsWithCredentials(api, name, draft.credentials ?? ""),
    enabled: kind === "claude" && (change || draft.credentials !== null),
    staleTime: 60 * 60 * 1000,
  });

  if (kind === null) {
    return (
      <Redirect
        href={{ pathname: "/agent/[name]/provider/choose", params: { name } }}
      />
    );
  }
  const catalog = resource.data?.catalog;
  const entry = catalog?.providers[kind];
  const current = change
    ? (resource.data?.provider.model ?? entry?.default_model ?? "")
    : catalog
      ? modelStepInitialModel(kind, draft.model, catalog)
      : "";
  const pending = change
    ? apply.isPending && apply.variables.type === "model"
      ? apply.variables.model
      : null
    : provision.isPending
      ? draft.model
      : null;

  const pick = (model: string) => {
    if (change) {
      apply.mutate({ type: "model", model });
      return;
    }
    update({ model });
    if (contextPolicyToOffer(kind, entry, model)) openStep("context");
    else finish(model);
  };

  return (
    <ProviderStepScreen title="Model">
      {catalog ? (
        <ModelList
          kind={kind}
          options={buildModelOptions(
            kind,
            entry,
            openRouterModels.data,
            claudeModels.data,
          )}
          loading={openRouterModels.isLoading || claudeModels.isLoading}
          selected={kind === "claude" ? canonicalClaudeModel(current) : current}
          pending={pending}
          onPick={pick}
        />
      ) : (
        <FormSectionSkeleton rows={4} label="Loading models" />
      )}
    </ProviderStepScreen>
  );
}
