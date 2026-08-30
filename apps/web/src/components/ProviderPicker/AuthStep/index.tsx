import { AuthFlow } from "@/components/AuthFlow";
import { ProgressBar } from "@/components/ProgressBar";
import { claudeProvider } from "@/api";

type AuthStartResult = claudeProvider.OAuthStartResult;

export function AuthStep({
  agentName,
  authStart,
  startError,
  onCredentialsReady,
  onBack,
}: {
  agentName: string;
  authStart: AuthStartResult | null;
  startError: string | null;
  onCredentialsReady: (credentials: string) => void;
  onBack: () => void;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      {authStart ? (
        <AuthFlow
          authUrl={authStart.auth_url}
          onSubmitCode={async (code) => {
            const creds = await claudeProvider.completeOAuth(
              agentName,
              authStart.session_id,
              code,
            );
            onCredentialsReady(creds);
          }}
          onBack={onBack}
        />
      ) : startError ? (
        <p className="text-xs text-destructive text-center py-2">
          {startError}
        </p>
      ) : (
        <ProgressBar message="starting authentication..." />
      )}
    </div>
  );
}
