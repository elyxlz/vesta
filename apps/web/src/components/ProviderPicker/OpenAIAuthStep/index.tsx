import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { openaiProvider } from "@/api";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/utils";
import { ProviderStep } from "../ProviderStep";
import { OpenAILogo } from "../logos";

export function OpenAIAuthStep({
  authStart,
  startError,
  onCredentialsReady,
  onCancel,
}: {
  authStart: openaiProvider.OAuthStartResult | null;
  startError: string | null;
  onCredentialsReady: (credentials: string) => void;
  onCancel: () => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  if (startError) {
    return (
      <p className="py-2 text-center text-xs text-destructive">{startError}</p>
    );
  }
  if (!authStart) {
    return (
      <p className="py-2 text-center text-xs text-muted-foreground">
        starting authentication...
      </p>
    );
  }

  const submit = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      onCredentialsReady(
        await openaiProvider.completeOAuth(authStart.session_id),
      );
    } catch (caught: unknown) {
      setError(errorMessage(caught, "verification failed"));
      setSubmitting(false);
    }
  };

  return (
    <ProviderStep
      logo={<OpenAILogo />}
      title="sign in to ChatGPT"
      subtitle="open the link, enter this one-time code, then continue."
      submitLabel={submitting ? "checking sign-in..." : "continue"}
      submitDisabled={submitting}
      onSubmit={() => void submit()}
      onCancel={onCancel}
      error={error || undefined}
      oauthLink={
        <a
          href={authStart.auth_url}
          target="_blank"
          rel="noopener"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          {authStart.auth_url}
        </a>
      }
    >
      <div className="flex w-full items-center justify-center gap-2 rounded-xl border bg-input/30 p-3">
        <code className="text-lg font-semibold tracking-[0.2em]">
          {authStart.user_code}
        </code>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label={copied ? "copied" : "copy one-time code"}
          onClick={() => {
            void navigator.clipboard
              .writeText(authStart.user_code)
              .then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              })
              .catch(() => setError("could not copy the code"));
          }}
        >
          {copied ? <Check /> : <Copy />}
        </Button>
      </div>
    </ProviderStep>
  );
}
