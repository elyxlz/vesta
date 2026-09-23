import { Redirect, useLocalSearchParams } from "expo-router";
import { planContextOptions, planFromCredentials } from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import {
  useFinishSetup,
  useProviderChange,
  useProviderResource,
} from "@/agent/settings/provider-actions";
import { useProviderDraft } from "@/agent/settings/provider-draft";
import { contextPolicyToOffer } from "@/agent/settings/provider-model";
import {
  ContextList,
  ProviderStepScreen,
} from "@/agent/settings/provider-steps";

// Setup's last step, or a change to the signed-in agent's window. Claude gates the larger
// windows on the plan: setup reads it from the fresh credentials, a change from the agent.
export default function ProviderContextScreen() {
  const { name } = useAgent();
  const change = useLocalSearchParams<{ change?: string }>().change === "1";
  const { resource, signedInKind } = useProviderResource();
  const { draft } = useProviderDraft();
  const { finish, provision } = useFinishSetup();
  const apply = useProviderChange();
  const kind = change ? signedInKind : draft.kind;
  const provider = resource.data?.provider;
  const model = change ? (provider?.model ?? "") : draft.model;
  const policy =
    kind === null
      ? null
      : contextPolicyToOffer(
          kind,
          resource.data?.catalog.providers[kind],
          model,
        );

  if (kind === null || (resource.data && !policy)) {
    return (
      <Redirect
        href={{ pathname: "/agent/[name]/provider/choose", params: { name } }}
      />
    );
  }
  const plan = change
    ? (provider?.plan ?? null)
    : kind === "claude" && draft.credentials !== null
      ? planFromCredentials(draft.credentials)
      : null;
  const options = policy ? planContextOptions(policy, plan) : null;
  const pending = change
    ? apply.isPending && apply.variables.type === "context"
      ? apply.variables.tokens
      : null
    : provision.isPending && provision.variables.maxContextTokens !== undefined
      ? provision.variables.maxContextTokens
      : null;

  return (
    <ProviderStepScreen title="Context window">
      {options ? (
        <ContextList
          presets={options.presets}
          selected={
            change
              ? (provider?.max_context_tokens ?? options.initial)
              : options.initial
          }
          pending={pending}
          onPick={(tokens) => {
            if (change) apply.mutate({ type: "context", tokens });
            else finish(model, tokens);
          }}
        />
      ) : null}
    </ProviderStepScreen>
  );
}
