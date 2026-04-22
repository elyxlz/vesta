import { useNavigate } from "react-router-dom";
import { AuthFlow } from "@/components/AuthFlow";
import { deleteAgent, type AuthStartResult } from "@/api";
import { useGateway } from "@/providers/GatewayProvider";
import { useOnboarding } from "@/stores/use-onboarding";

export function AuthStep({
  agentName,
  authStart,
  onDone,
}: {
  agentName: string;
  authStart: AuthStartResult;
  onDone: () => void;
}) {
  const navigate = useNavigate();
  const { agents } = useGateway();
  const setStep = useOnboarding((s) => s.setStep);

  return (
    <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
      <AuthFlow
        agentName={agentName}
        authUrl={authStart.auth_url}
        sessionId={authStart.session_id}
        onCancel={async () => {
          if (agents.length > 1) {
            navigate("/");
          } else {
            setStep("name");
          }
          try {
            await deleteAgent(agentName);
          } catch {
            /* best-effort cleanup */
          }
        }}
        onComplete={onDone}
      />
    </div>
  );
}
