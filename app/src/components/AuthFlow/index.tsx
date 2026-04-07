import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProgressBar } from "@/components/ProgressBar";
import { submitAuthCode } from "@/api";
import { fadeSlide } from "@/lib/motion";

interface AuthFlowProps {
  agentName: string;
  authUrl: string;
  sessionId: string;
  onCancel?: () => void;
  onComplete?: () => void;
}

type AuthState = "waiting" | "submitting" | "error";

export function AuthFlow({
  agentName,
  authUrl,
  sessionId,
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

  const handleSubmit = async () => {
    if (!code.trim() || authState === "submitting") return;
    setAuthState("submitting");
    setError("");

    try {
      await submitAuthCode(agentName, sessionId, code.trim());
      onComplete?.();
    } catch (e: unknown) {
      setError((e as { message?: string })?.message || "verification failed");
      setAuthState("error");
      setCode("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSubmit();
  };

  const content = (() => {
    if (authState === "submitting") {
      return (
        <div className="flex min-w-0 w-full max-w-full flex-col items-center gap-3">
          <p className="text-sm text-muted-foreground">setting up agent...</p>
          <ProgressBar message="this may take a couple of mins" />
        </div>
      );
    }

    return (
      <div className="flex min-w-0 w-full max-w-full flex-col gap-3">
        {authUrl && (
          <div className="flex min-h-0 min-w-0 w-full max-w-full items-center gap-1.5 overflow-hidden">
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
              onClick={copyAuthUrl}
            >
              {copied ? <Check /> : <Copy />}
            </Button>
          </div>
        )}
        <p className="text-xs text-muted-foreground text-center">
          paste the code from the browser below
        </p>
        <Input
          placeholder="paste code here"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
          className="w-full text-center text-sm"
        />
        <Button
          onClick={handleSubmit}
          disabled={!code.trim()}
          size="sm"
          className="w-full"
        >
          submit
        </Button>
        {error && (
          <p className="text-xs text-destructive">{error}</p>
        )}
        {onCancel && (
          <Button
            variant="link"
            onClick={onCancel}
            className="self-center h-auto px-0 py-0 text-xs font-normal text-muted-foreground underline underline-offset-4 hover:bg-transparent hover:text-foreground"
          >
            cancel
          </Button>
        )}
      </div>
    );
  })();

  return (
    <AnimatePresence mode="wait">
      <motion.div key={authState} {...fadeSlide} className="min-w-0 w-full max-w-full">
        {content}
      </motion.div>
    </AnimatePresence>
  );
}
