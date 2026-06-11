import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  FieldGroup,
  Field,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import { fade } from "@/lib/motion";
import { errorMessage } from "@/lib/utils";
import { startHostedLogin } from "@/lib/pkce";
import { isTauri } from "@/lib/env";
import { useAuth } from "@/providers/AuthProvider";

// VITE_VESTAD_HOSTED=true means the SPA was bundled by vestad itself, so
// window.location.origin already points at the right vestad instance.
// Anything else (tauri, vite dev, or self-hosted on a non-vestad server) needs
// the user to enter the vestad host explicitly.
const needHostInput = import.meta.env.VITE_VESTAD_HOSTED !== "true";

function normalizeHost(input: string): string {
  const trimmed = input.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(trimmed)) return `https://${trimmed}`;
  return trimmed;
}

export function Connect() {
  const { connected, connect, sessionExpired } = useAuth();
  const [apiKey, setApiKey] = useState("");
  const [host, setHost] = useState("");
  const [error, setError] = useState("");
  const [details, setDetails] = useState("");
  const [showDetails, setShowDetails] = useState(false);
  const [busy, setBusy] = useState(false);
  // In the native app (and any vesta-account surface) we lead with "continue
  // with vesta account"; `selfHost` flips to the host+key form for people
  // running their own box. Only ever set on Tauri (the web bundles know which
  // form they need from `managed`).
  const [selfHost, setSelfHost] = useState(false);
  // On a vestad-served bundle we don't yet know if this is a hosted (vesta.run)
  // box. Probe /info.managed: managed boxes log in via the vesta.run handoff
  // (PKCE, issue #19) since the user never gets the api_key; self-hosted boxes
  // keep the paste-key form. `null` = still probing.
  const [managed, setManaged] = useState<boolean | null>(
    needHostInput ? false : null,
  );

  useEffect(() => {
    if (managed !== null) return;
    let cancelled = false;
    void (async () => {
      try {
        const resp = await fetch(`${window.location.origin}/info`, {
          signal: AbortSignal.timeout(5000),
        });
        const data = await resp.json();
        if (!cancelled) setManaged(data?.managed === true);
      } catch {
        if (!cancelled) setManaged(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [managed]);

  if (connected) return <Navigate to="/" replace />;

  const handleConnect = async () => {
    if (!apiKey.trim() || busy) return;
    if (needHostInput && !host.trim()) return;
    setBusy(true);
    setError("");
    setDetails("");

    try {
      const url = needHostInput ? normalizeHost(host) : window.location.origin;
      await connect(url, apiKey.trim());
    } catch (e: unknown) {
      const msg = errorMessage(e, "connection failed");
      setError("could not reach server");
      if (msg !== "could not reach server") setDetails(msg);
      setBusy(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleConnect();
  };

  const handleHostedSignIn = () => {
    if (busy) return;
    setBusy(true);
    setError("");
    // Web: full-navigates to vesta.run/api/authorize. Native: opens the system
    // browser and waits on a loopback redirect (the promise resolves only after
    // a successful exchange, which itself navigates). On failure we stay put.
    void startHostedLogin().catch(() => {
      setError("could not start sign-in");
      setBusy(false);
    });
  };

  // Hosted (vesta.run) box: the user never has an api_key, so log in through the
  // control plane. Render nothing while still probing /info to avoid flashing the
  // wrong form.
  if (managed === null) {
    return <div className="flex h-full flex-col p-page" />;
  }
  // Lead with the vesta account on a managed box (web) and in the native app,
  // unless the native user chose self-hosting.
  if ((managed || isTauri) && !selfHost) {
    return (
      <div className="flex h-full flex-col p-page">
        <div className="flex flex-1 items-center justify-center">
          <div className="flex flex-col items-center gap-3 w-[240px] max-w-full px-4 text-center">
            <h1 className="text-base font-semibold">sign in</h1>
            <FieldDescription className="text-center">
              {sessionExpired
                ? "your session expired — sign in again"
                : "continue with your vesta account"}
            </FieldDescription>
            <Button
              type="button"
              onClick={handleHostedSignIn}
              disabled={busy}
              className="w-full"
            >
              {busy
                ? isTauri
                  ? "waiting for browser..."
                  : "redirecting..."
                : "continue with vesta account"}
            </Button>
            <AnimatePresence>
              {error && (
                <motion.p {...fade} className="text-xs text-destructive">
                  {error}
                </motion.p>
              )}
            </AnimatePresence>
            {isTauri && (
              <button
                type="button"
                onClick={() => {
                  setError("");
                  setSelfHost(true);
                }}
                className="text-xs text-muted-foreground underline-offset-4 hover:underline"
              >
                self-hosting? connect with a key
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-page">
      <div className="flex flex-1 items-center justify-center">
        <form
          onSubmit={handleSubmit}
          className="flex flex-col items-center gap-3 w-[240px] max-w-full px-4"
        >
          <div className="flex flex-col items-center gap-1 text-center">
            <h1 className="text-base font-semibold">connect</h1>
            {sessionExpired && (
              <FieldDescription className="text-center">
                your session expired — connect again
              </FieldDescription>
            )}
          </div>

          <FieldGroup className="gap-3">
            {needHostInput && (
              <Field>
                <FieldLabel htmlFor="host" className="sr-only">
                  Host
                </FieldLabel>
                <Input
                  id="host"
                  type="url"
                  placeholder="host"
                  autoComplete="url"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  className="text-center"
                />
                <FieldDescription className="text-center">
                  the tunnel url vestad printed on first run, e.g.
                  https://name.trycloudflare.com
                </FieldDescription>
              </Field>
            )}
            <Field>
              <FieldLabel htmlFor="key" className="sr-only">
                Key
              </FieldLabel>
              <Input
                id="key"
                name="password"
                type="password"
                placeholder="key"
                autoComplete="current-password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="text-center"
              />
              <FieldDescription className="text-center">
                the api key from ~/.config/vesta/vestad/api-key
              </FieldDescription>
            </Field>
          </FieldGroup>

          <Button
            type="submit"
            disabled={!apiKey.trim() || (needHostInput && !host.trim()) || busy}
            className="w-full"
          >
            {busy ? "connecting..." : "connect"}
          </Button>

          {isTauri && selfHost && (
            <button
              type="button"
              onClick={() => {
                setError("");
                setDetails("");
                setSelfHost(false);
              }}
              className="text-xs text-muted-foreground underline-offset-4 hover:underline"
            >
              use a vesta account instead
            </button>
          )}

          <AnimatePresence>
            {error && (
              <motion.div
                {...fade}
                className="flex flex-col items-center gap-1 text-center"
              >
                <p className="text-xs">
                  <span className="text-destructive">{error}</span>
                  {details && (
                    <>
                      <span className="text-foreground"> · </span>
                      <button
                        type="button"
                        aria-expanded={showDetails}
                        onClick={() => setShowDetails(!showDetails)}
                        className="text-foreground underline-offset-4 hover:underline"
                      >
                        {showDetails ? "hide details" : "show details"}
                      </button>
                    </>
                  )}
                </p>
                {showDetails && details && (
                  <p className="text-xs text-muted-foreground break-all">
                    {details}
                  </p>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </form>
      </div>
    </div>
  );
}
