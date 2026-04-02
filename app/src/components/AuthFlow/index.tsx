import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProgressBar } from "@/components/ProgressBar";
import { authenticate, submitAuthCode } from "@/api";
import { isTauri } from "@/lib/env";

interface AuthFlowProps {
  agentName: string;
  onCancel?: () => void;
  onComplete?: () => void;
}

type AuthState = "starting" | "waiting" | "submitting" | "error";

export function AuthFlow({ agentName, onCancel, onComplete }: AuthFlowProps) {
  const [authState, setAuthState] = useState<AuthState>("starting");
  const [authUrl, setAuthUrl] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const startAuth = async () => {
      try {
        const result = await authenticate(agentName);
        setAuthUrl(result.auth_url);
        setSessionId(result.session_id);
        setAuthState("waiting");

        if (isTauri) {
          try {
            const { openUrl } = await import("@tauri-apps/plugin-opener");
            await openUrl(result.auth_url);
          } catch {
            window.open(result.auth_url, "_blank");
          }
        } else {
          window.open(result.auth_url, "_blank");
        }
      } catch (e: unknown) {
        setError((e as { message?: string })?.message || "authentication failed");
        setAuthState("error");
      }
    };
    startAuth();
  }, [agentName]);

  const handleSubmit = useCallback(async () => {
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
  }, [code, authState, agentName, sessionId, onComplete]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") handleSubmit();
    },
    [handleSubmit],
  );

  if (authState === "starting") {
    return (
      <div className="flex flex-col items-center gap-3 w-full animate-fade-slide-in">
        <p className="text-sm text-muted-foreground">starting authentication...</p>
        <ProgressBar message="waiting..." />
      </div>
    );
  }

  if (authState === "submitting") {
    return (
      <div className="flex flex-col items-center gap-3 w-full animate-fade-slide-in">
        <p className="text-sm text-muted-foreground">verifying code...</p>
        <ProgressBar message="verifying..." />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-3 w-full max-w-[260px] animate-fade-slide-in">
      {authUrl && (
        <a
          href={authUrl}
          target="_blank"
          rel="noopener"
          className="text-xs text-muted-foreground hover:text-foreground truncate max-w-full"
        >
          {authUrl.length > 50 ? `${authUrl.slice(0, 50)}...` : authUrl}
        </a>
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
        <p className="text-xs text-destructive animate-shake">{error}</p>
      )}
      {onCancel && (
        <Button
          variant="link"
          size="xs"
          onClick={onCancel}
        >
          cancel
        </Button>
      )}
    </div>
  );
}
