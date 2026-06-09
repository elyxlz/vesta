import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { setHostedConnection } from "@/lib/connection";
import { completeHostedLogin } from "@/lib/pkce";

// OAuth redirect target for the hosted login handoff (issue #19). The control
// plane bounces here with `?code=...&state=...`; we exchange the code over the
// back channel for an access token, persist it, then enter the app.
export function Callback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  // StrictMode double-invokes effects in dev; the code is single-use, so guard.
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      setError("missing code");
      return;
    }

    void (async () => {
      try {
        const { accessToken, expiresIn } = await completeHostedLogin(
          code,
          state,
        );
        setHostedConnection(window.location.origin, accessToken, expiresIn);
        // Strip the code/state from the URL, then enter the app with a full
        // load so providers re-read the now-present connection.
        window.history.replaceState(null, "", "/");
        window.location.assign("/");
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "sign-in failed");
      }
    })();
  }, [params]);

  return (
    <div className="flex h-full flex-1 flex-col items-center justify-center gap-3 p-page text-center">
      {error ? (
        <>
          <p className="text-xs text-destructive">{error}</p>
          <Button onClick={() => navigate("/connect", { replace: true })}>
            back to sign-in
          </Button>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">signing in...</p>
      )}
    </div>
  );
}
