import { useState } from "react";
import { Input } from "@/components/ui/input";
import { ProviderStep } from "@/components/ProviderPicker/ProviderStep";
import { OAuthLink } from "@/components/ProviderPicker/OAuthLink";
import { ClaudeLogo } from "@/components/ProviderPicker/logos";
import { errorMessage } from "@/lib/utils";

interface AuthFlowProps {
  authUrl: string;
  onSubmitCode: (code: string) => Promise<void>;
  onBack?: () => void;
  onComplete?: () => void;
}

type AuthState = "waiting" | "submitting" | "error";

export function AuthFlow({
  authUrl,
  onSubmitCode,
  onBack,
  onComplete,
}: AuthFlowProps) {
  const [authState, setAuthState] = useState<AuthState>("waiting");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  const submitting = authState === "submitting";

  const submit = async () => {
    if (!code.trim() || submitting) return;
    setAuthState("submitting");
    setError("");
    try {
      await onSubmitCode(code.trim());
      onComplete?.();
    } catch (e: unknown) {
      setError(errorMessage(e, "verification failed"));
      setAuthState("error");
      setCode("");
    }
  };

  return (
    <ProviderStep
      logo={<ClaudeLogo />}
      title="sign in to claude"
      subtitle="open the link, sign in, then paste the code below."
      oauthLink={authUrl ? <OAuthLink url={authUrl} /> : undefined}
      submitLabel={submitting ? "verifying code..." : "continue"}
      submitDisabled={!code.trim() || submitting}
      onSubmit={() => {
        void submit();
      }}
      onBack={onBack}
      error={error || undefined}
    >
      <Input
        placeholder="paste code here"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        autoFocus
        disabled={submitting}
        className="h-11 w-full text-center"
      />
    </ProviderStep>
  );
}
