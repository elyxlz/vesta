import { use } from "react";
import { useRouter } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  contextForModel,
  getProvider,
  providerResult,
  provisionAgent,
  setContextWindow,
  setModel,
  type ProviderKind,
  type ProviderSelection,
} from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import { useProviderDraft } from "@/agent/settings/provider-draft";
import { useToast } from "@/components/native-toast";
import { ControllerContext } from "@/controller/context";
import { useSession } from "@/session/SessionProvider";

export function useProviderResource() {
  const { api } = useSession();
  const { name } = useAgent();
  const resource = useQuery({
    queryKey: ["provider", name],
    queryFn: () => getProvider(api, name),
  });
  const provider = resource.data?.provider;
  const signedInKind: ProviderKind | null =
    provider && provider.kind !== "none" && provider.authed
      ? provider.kind
      : null;
  return { resource, signedInKind };
}

// Provisioning is this client's own request on the agent: the orb reads "signing in..."
// app-wide until the gateway answers, then the roster's restart carries the rest. The flow ends
// back on agent settings, where that orb is.
function useProvision() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { showError } = useToast();
  const controller = use(ControllerContext);
  return useMutation({
    mutationFn: (selection: ProviderSelection) =>
      provisionAgent(api, name, selection),
    onMutate: () => controller?.requests.set(name, "authenticating"),
    onSuccess: () => {
      controller?.requests.clear(name);
      void queryClient.invalidateQueries({ queryKey: ["provider", name] });
      router.dismissTo({
        pathname: "/agent/[name]/settings",
        params: { name },
      });
    },
    onError: (error) => {
      controller?.requests.set(
        name,
        "idle",
        error instanceof Error ? error.message : "Provider sign-in failed",
      );
      showError(error, "Provider sign-in failed");
    },
  });
}

type Change =
  { type: "model"; model: string } | { type: "context"; tokens: number };

// A model or context change on a signed-in agent applies at once and returns to the summary.
export function useProviderChange() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { showError } = useToast();
  return useMutation({
    mutationFn: async (next: Change) => {
      if (next.type === "model") await setModel(api, name, next.model);
      else await setContextWindow(api, name, next.tokens);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["provider", name] });
      router.back();
    },
    onError: (error) => showError(error, "Could not update the provider"),
  });
}

const STEP_PATHS = {
  choose: "/agent/[name]/provider/choose",
  "sign-in": "/agent/[name]/provider/sign-in",
  model: "/agent/[name]/provider/model",
  context: "/agent/[name]/provider/context",
} as const;

// `change` opens the model or context step for a signed-in agent instead of a setup.
export function useOpenProviderStep() {
  const router = useRouter();
  const { name } = useAgent();
  return (step: keyof typeof STEP_PATHS, change = false) =>
    router.push({
      pathname: STEP_PATHS[step],
      params: change ? { name, change: "1" } : { name },
    });
}

// The setup's last step: the draft plus the chosen model and window become one selection.
// A model with no window to choose takes its policy's default; OpenRouter models carry their own.
export function useFinishSetup() {
  const { draft } = useProviderDraft();
  const { resource } = useProviderResource();
  const provision = useProvision();
  const finish = (model: string, maxContextTokens?: number) => {
    const kind = draft.kind;
    if (kind === null) return;
    const tokens =
      maxContextTokens ??
      (kind === "openrouter"
        ? 0
        : (contextForModel(resource.data?.catalog.providers[kind], model)
            ?.default ?? 0));
    const selection = providerResult(
      kind,
      draft.credentials,
      draft.key,
      model,
      tokens,
    );
    if (selection) provision.mutate(selection);
  };
  return { finish, provision };
}
