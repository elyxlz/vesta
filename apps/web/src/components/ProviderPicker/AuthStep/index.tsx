import { AuthFlow } from "@/components/AuthFlow";
import { ProgressBar } from "@/components/ProgressBar";
import { claudeProvider } from "@/api";

type AuthStartResult = claudeProvider.OAuthStartResult;

export function AuthStep({
  authStart,
  startError,
  onCredentialsReady,
  onCancel,
}: {
  authStart: AuthStartResult | null;
  startError: string | null;
  onCredentialsReady: (credentials: string) => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      {authStart ? (
        <AuthFlow
          authUrl={authStart.auth_url}
          onSubmitCode={async (code) => {
            const creds = await claudeProvider.completeOAuth(
              authStart.session_id,
              code,
            );
            onCredentialsReady(creds);
          }}
          onCancel={onCancel}
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
