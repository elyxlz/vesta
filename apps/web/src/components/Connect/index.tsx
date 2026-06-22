import { useEffect, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel, FieldDescription } from "@/components/ui/field";
import { LogoText } from "@/components/Logo/LogoText";
import { ProgressBar } from "@/components/ProgressBar";
import { fade } from "@/lib/motion";
import { errorMessage } from "@/lib/utils";
import { startHostedLogin } from "@/lib/pkce";
import { isTauri } from "@/lib/env";
import { parseConnectLink } from "@/lib/connection";
import { useAuth } from "@/providers/AuthProvider";

// VITE_VESTAD_HOSTED=true means the SPA was bundled by vestad itself, so
// window.location.origin already points at the right vestad instance.
// Anything else (tauri, vite dev, or self-hosted on a non-vestad server) needs
// the user to enter the vestad host explicitly.
const needHostInput = import.meta.env.VITE_VESTAD_HOSTED !== "true";

// A soft rise-and-fade so the connect card settles in rather than snapping on.
const connectEntrance = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.3, ease: "easeOut" },
} as const;

function ConnectHeader() {
  return (
    <div className="mb-2 flex flex-col items-center gap-1.5">
      <LogoText />
      <p className="text-sm text-muted-foreground">your unfair advantage</p>
    </div>
  );
}

export function Connect() {
  const { connected, connect, sessionExpired } = useAuth();
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // In the native app (and any vesta-account surface) we lead with "continue
  // with vesta account"; `selfHost` flips to the connect-link form for people
  // running their own agent. Only ever set on Tauri (the web bundles know which
  // form they need from `managed`).
  const [selfHost, setSelfHost] = useState(false);
  // On a vestad-served bundle we don't yet know if this is a hosted (vesta.run)
  // instance. Probe /info.managed: managed instances log in via the vesta.run
  // handoff (PKCE, issue #19) since the user never gets the api_key; self-hosted
  // ones keep the connect-link form. `null` = still probing.
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

  // One brain-dead field: paste the whole connect link `vestad` printed and we
  // pull out both the host and the key. A vestad-served bundle uses its own
  // origin (the link's host is irrelevant there); the native app has no origin
  // to assume, so it relies on the host from the link.
  const handleConnect = async () => {
    if (busy) return;
    const link = parseConnectLink(value);
    if (!link) {
      setError("paste your connect link");
      inputRef.current?.focus();
      return;
    }
    const url = needHostInput ? link.host : window.location.origin;
    setBusy(true);
    setError("");

    try {
      await connect(url, link.key);
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

  // Still probing /info to avoid flashing the wrong form. Keep the logo in place
  // so resolving to a form doesn't jump the layout.
  if (managed === null) {
    return (
      <div className="flex h-full flex-col p-page">
        <div className="flex flex-1 items-center justify-center">
          <motion.div
            {...connectEntrance}
            className="flex w-[280px] max-w-full flex-col items-center gap-4 px-4 text-center"
          >
            <ConnectHeader />
            <div className="w-full">
              <ProgressBar />
            </div>
          </motion.div>
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
          <motion.div
            {...connectEntrance}
            className="flex w-[280px] max-w-full flex-col items-center gap-4 px-4 text-center"
          >
            <ConnectHeader />
            {sessionExpired && (
              <FieldDescription className="text-center">
                your session expired, sign in again
              </FieldDescription>
            )}
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
                self-hosting? connect with a link
              </button>
            )}
          </motion.div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-page">
      <div className="flex flex-1 items-center justify-center">
        <motion.form
          {...connectEntrance}
          onSubmit={handleSubmit}
          className="flex w-[280px] max-w-full flex-col items-center gap-4 px-4"
        >
          <ConnectHeader />
          {sessionExpired && (
            <FieldDescription className="text-center">
              your session expired, connect again
            </FieldDescription>
          )}

          <Field className="w-full">
            <FieldLabel htmlFor="connect-link" className="sr-only">
              Connect link
            </FieldLabel>
            <Input
              ref={inputRef}
              id="connect-link"
              type="text"
              placeholder="paste your connect link"
              autoComplete="off"
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="text-center"
            />
          </Field>

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
        </motion.form>
      </div>
    </div>
  );
}
