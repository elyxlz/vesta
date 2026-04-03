import { AuthFlow } from "@/components/AuthFlow";
import type { AuthStartResult } from "@/api";

interface AuthStepProps {
  agentName: string;
  authStart: AuthStartResult;
  onCancel: () => void;
  onComplete: () => void;
}

export function AuthStep({
  agentName,
  authStart,
  onCancel,
  onComplete,
}: AuthStepProps) {
  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
      <AuthFlow
        agentName={agentName}
        authUrl={authStart.auth_url}
        sessionId={authStart.session_id}
        onCancel={onCancel}
        onComplete={onComplete}
      />
    </div>
  );
}
