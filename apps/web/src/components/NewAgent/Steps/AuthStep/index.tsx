import { AuthFlow } from "@/components/AuthFlow";
import { ProgressBar } from "@/components/ProgressBar";
import { completeAuth, type AuthStartResult } from "@/api";

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
    <div className="flex w-[260px] max-w-full flex-col items-center gap-3 px-4">
      {authStart ? (
        <AuthFlow
          authUrl={authStart.auth_url}
          onSubmitCode={async (code) => {
            const creds = await completeAuth(authStart.session_id, code);
            onCredentialsReady(creds);
          }}
          onCancel={onCancel}
        />
      ) : startError ? (
        <div className="flex flex-col items-center gap-3 py-2">
          <p className="text-xs text-destructive text-center">{startError}</p>
        </div>
      ) : (
        <ProgressBar message="starting authentication..." />
      )}
    </div>
  );
}
