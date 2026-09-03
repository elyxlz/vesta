import { AuthStep } from "./AuthStep";
import { OpenAIAuthStep } from "./OpenAIAuthStep";
import type { ProviderKind } from "@vesta/core";
import { type AuthStartResult } from "./provider-flow";

export function ProviderAuthStep({
  agentName,
  provider,
  authStart,
  startError,
  onCredentialsReady,
  onBack,
}: {
  agentName: string;
  provider: ProviderKind | null;
  authStart: AuthStartResult | null;
  startError: string | null;
  onCredentialsReady: (credentials: string) => void;
  onBack: () => void;
}) {
  if (provider === "claude") {
    return (
      <AuthStep
        agentName={agentName}
        authStart={authStart}
        startError={startError}
        onCredentialsReady={onCredentialsReady}
        onBack={onBack}
      />
    );
  }
  if (provider === "openai") {
    return (
      <OpenAIAuthStep
        agentName={agentName}
        authStart={
          authStart !== null && "user_code" in authStart ? authStart : null
        }
        startError={startError}
        onCredentialsReady={onCredentialsReady}
        onBack={onBack}
      />
    );
  }
  return null;
}
