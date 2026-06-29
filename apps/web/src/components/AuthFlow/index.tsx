import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProviderStep } from "@/components/ProviderPicker/ProviderStep";
import { ClaudeLogo } from "@/components/ProviderPicker/logos";
import { errorMessage } from "@/lib/utils";

interface AuthFlowProps {
  authUrl: string;
  onSubmitCode: (code: string) => Promise<void>;
  onCancel?: () => void;
  onComplete?: () => void;
}

type AuthState = "waiting" | "submitting" | "error";

export function AuthFlow({
  authUrl,
  onSubmitCode,
  onCancel,
  onComplete,
}: AuthFlowProps) {
  const [authState, setAuthState] = useState<AuthState>("waiting");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const copyAuthUrl = async () => {
    try {
      await navigator.clipboard.writeText(authUrl);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = authUrl;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

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
      className="gap-2"
      logo={<ClaudeLogo />}
      title="sign in to claude"
      subtitle="open the link, sign in, then paste the code below."
      oauthLink={
        authUrl ? (
          <div className="mt-2 flex w-full min-w-0 max-w-full flex-col gap-1">
            <div className="flex min-h-0 w-full min-w-0 max-w-full items-center gap-1.5 overflow-hidden">
              <a
                href={authUrl}
                target="_blank"
                rel="noopener"
                className="block min-w-0 flex-1 truncate text-xs text-muted-foreground hover:text-foreground"
              >
                {authUrl}
              </a>
              <Button
                variant="ghost"
                size="icon-xs"
                className="shrink-0"
                type="button"
                aria-label={copied ? "copied" : "copy auth link"}
                onClick={copyAuthUrl}
              >
                {copied ? <Check /> : <Copy />}
              </Button>
              <span className="sr-only" role="status" aria-live="polite">
                {copied ? "copied" : ""}
              </span>
            </div>
          </div>
        ) : undefined
      }
      submitLabel={submitting ? "verifying code..." : "continue"}
      submitDisabled={!code.trim() || submitting}
      onSubmit={submit}
      onCancel={onCancel}
      error={error || undefined}
    >
      <Input
        placeholder="paste code here"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        autoFocus
        disabled={submitting}
        className="w-full text-center"
      />
    </ProviderStep>
  );
}
