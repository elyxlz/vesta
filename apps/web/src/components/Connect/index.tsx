import { useEffect, useRef, useState } from "react";
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
import { LogoText } from "@/components/Logo/LogoText";
import { ProgressBar } from "@/components/ProgressBar";
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
  const { connected, connect } = useAuth();
  const [apiKey, setApiKey] = useState("");
  const [host, setHost] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const hostRef = useRef<HTMLInputElement>(null);
  const keyRef = useRef<HTMLInputElement>(null);
  // In the native app (and any vesta-account surface) we lead with "continue
  // with vesta account"; `selfHost` flips to the host+key form for people
  // running their own agent. Only ever set on Tauri (the web bundles know which
  // form they need from `managed`).
  const [selfHost, setSelfHost] = useState(false);
  // On a vestad-served bundle we don't yet know if this is a hosted (vesta.run)
  // instance. Probe /info.managed: managed instances log in via the vesta.run
  // handoff (PKCE, issue #19) since the user never gets the api_key; self-hosted
  // ones keep the paste-key form. `null` = still probing.
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
    if (busy) return;
    if (needHostInput && !host.trim()) {
      hostRef.current?.focus();
      return;
    }
    if (!apiKey.trim()) {
      keyRef.current?.focus();
      return;
    }
    setBusy(true);
    setError("");

    try {
      const url = needHostInput ? normalizeHost(host) : window.location.origin;
      await connect(url, apiKey.trim());
    } catch (e: unknown) {
      setError(errorMessage(e, "connection failed"));
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

  // Still probing /info to avoid flashing the wrong form.
  if (managed === null) {
    return (
      <div className="flex h-full flex-col p-page">
        <div className="flex flex-1 items-center justify-center">
          <div className="w-[240px] max-w-full px-4">
            <ProgressBar />
          </div>
        </div>
      </div>
    );
  }
  // Hosted (vesta.run): the user never has an api_key, so log in through the
  // control plane. Lead with the vesta account on a managed instance (web) and
  // in the native app, unless the native user chose self-hosting.
  if ((managed || isTauri) && !selfHost) {
    return (
      <div className="flex h-full flex-col p-page">
        <div className="flex flex-1 items-center justify-center">
          <div className="flex flex-col items-center gap-3 w-[240px] max-w-full px-4 text-center">
            <LogoText className="mb-2" />
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
                <motion.p
                  {...fade}
                  role="alert"
                  className="text-xs text-destructive"
                >
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
                className="px-3 py-3 -my-3 text-xs text-muted-foreground underline-offset-4 hover:underline"
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
          <LogoText className="mb-2" />

          <FieldGroup className="gap-3">
            {needHostInput && (
              <Field>
                <FieldLabel htmlFor="host" className="sr-only">
                  Host
                </FieldLabel>
                <Input
                  ref={hostRef}
                  id="host"
                  type="url"
                  placeholder="fox-mybox.example.com"
                  autoComplete="url"
                  autoFocus
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  className="text-center"
                />
                <FieldDescription className="text-center">
                  the url vestad printed on first run
                </FieldDescription>
              </Field>
            )}
            <Field>
              <FieldLabel htmlFor="key" className="sr-only">
                Key
              </FieldLabel>
              <Input
                ref={keyRef}
                id="key"
                name="password"
                type="password"
                placeholder="key"
                autoComplete="current-password"
                autoFocus={!needHostInput}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="text-center"
              />
              <FieldDescription className="text-center">
                the key vestad printed (also at ~/.config/vesta/vestad/api-key)
              </FieldDescription>
            </Field>
          </FieldGroup>

          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "connecting..." : "connect"}
          </Button>

          {isTauri && selfHost && (
            <button
              type="button"
              onClick={() => {
                setError("");
                setSelfHost(false);
              }}
              className="px-3 py-3 -my-3 text-xs text-muted-foreground underline-offset-4 hover:underline"
            >
              use a vesta account instead
            </button>
          )}

          <AnimatePresence>
            {error && (
              <motion.p
                {...fade}
                role="alert"
                className="text-xs text-destructive text-center break-all"
              >
                {error}
              </motion.p>
            )}
          </AnimatePresence>
        </form>
      </div>
    </div>
  );
}
