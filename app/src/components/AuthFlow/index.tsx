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
        <div className="flex flex-col items-center gap-3 w-full">
          <p className="text-sm text-muted-foreground">verifying code...</p>
          <ProgressBar message="verifying..." />
        </div>
      );
    }

    return (
      <div className="flex flex-col items-center gap-3 w-full max-w-[260px]">
        {authUrl && (
          <div className="flex items-center gap-1.5 max-w-full">
            <a
              href={authUrl}
              target="_blank"
              rel="noopener"
              className="text-xs text-muted-foreground hover:text-foreground truncate"
            >
              {authUrl.length > 50 ? `${authUrl.slice(0, 50)}...` : authUrl}
            </a>
            <Button
              variant="ghost"
              size="icon-xs"
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
          className="text-center text-sm"
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
            className="h-auto px-0 py-0 text-xs font-normal text-muted-foreground underline underline-offset-4 hover:bg-transparent hover:text-foreground"
          >
            cancel
          </Button>
        )}
      </div>
    );
  })();

  return (
    <AnimatePresence mode="wait">
      <motion.div key={authState} {...fadeSlide}>
        {content}
      </motion.div>
    </AnimatePresence>
  );
}
