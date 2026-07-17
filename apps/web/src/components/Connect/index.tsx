import { useEffect, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel, FieldDescription } from "@/components/ui/field";
import { LogoText } from "@/components/Logo/LogoText";
import { ProgressBar } from "@/components/ProgressBar";
import { fade } from "@/lib/motion";
import { errorMessage } from "@/lib/utils";
import { startHostedLogin } from "@/lib/pkce";
import { native } from "@/lib/native";
import { parseConnectLink } from "@/lib/connection";
import { useAuth } from "@/providers/AuthProvider";

// VITE_VESTAD_HOSTED=true means the SPA was bundled by vestad itself, so
// window.location.origin already points at the right vestad instance.
// Anything else (the desktop app, vite dev, or self-hosted on a non-vestad
// server) needs the user to enter the vestad host explicitly.
const needHostInput = import.meta.env.VITE_VESTAD_HOSTED !== "true";

const isDesktopApp = native.runtime === "electron";

// A soft rise-and-fade so the connect card settles in rather than snapping on.
const connectEntrance = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.3, ease: "easeOut" },
} as const;

function HostedSignInCard({
  sessionExpired,
  busy,
  error,
  onSignIn,
  onSelfHost,
}: {
  sessionExpired: boolean;
  busy: boolean;
  error: string;
  onSignIn: () => void;
  onSelfHost: () => void;
}) {
  return (
    <div className="flex h-full flex-col p-page">
      <div className="flex flex-1 items-center justify-center">
        <motion.div
          {...connectEntrance}
          className="flex w-[360px] max-w-full flex-col items-center gap-4 px-4 text-center"
        >
          <ConnectHeader />
          {sessionExpired && (
            <FieldDescription className="text-center">
              your session expired, sign in again
            </FieldDescription>
          )}
          <Button
            type="button"
            onClick={onSignIn}
            disabled={busy}
            className="max-w-full px-6"
          >
            {busy
              ? isDesktopApp
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
          {isDesktopApp && (
            <button
              type="button"
              onClick={onSelfHost}
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

function ConnectHeader() {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <LogoText />
      <p className="text-sm leading-none text-muted-foreground">
        your unfair advantage
      </p>
    </div>
  );
}

export function Connect() {
  const { connected, connect, sessionExpired } = useAuth();
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // In the desktop app (and any vesta-account surface) we lead with "continue
  // with vesta account"; `selfHost` flips to the connect-link form for people
  // running their own agent. Only ever set in the desktop app (the web bundles
  // know which form they need from `managed`).
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
    const probe = async () => {
      try {
        const resp = await fetch(`${window.location.origin}/info`, {
          signal: AbortSignal.timeout(5000),
        });
        const data = (await resp.json()) as { managed?: boolean };
        if (!cancelled) setManaged(data.managed === true);
      } catch {
        if (!cancelled) setManaged(false);
      }
    };
    void probe();
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
      setError(
        "that doesn't look like a connect link. paste the whole link vestad printed.",
      );
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

  const handleSubmit = (e: React.SubmitEvent) => {
    e.preventDefault();
    void handleConnect();
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
            className="flex w-[360px] max-w-full flex-col items-center gap-4 px-4 text-center"
          >
            <ConnectHeader />
            <div className="flex h-9 w-full items-center">
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
  if ((managed || isDesktopApp) && !selfHost) {
    return (
      <HostedSignInCard
        sessionExpired={sessionExpired}
        busy={busy}
        error={error}
        onSignIn={handleHostedSignIn}
        onSelfHost={() => {
          setError("");
          setSelfHost(true);
        }}
      />
    );
  }

  return (
    <div className="flex h-full flex-col p-page">
      <div className="flex flex-1 items-center justify-center">
        <motion.form
          {...connectEntrance}
          onSubmit={handleSubmit}
          className="flex w-[360px] max-w-full flex-col items-center gap-4 px-4"
        >
          <ConnectHeader />
          {sessionExpired && (
            <FieldDescription className="text-center">
              your session expired, connect again
            </FieldDescription>
          )}

          <Field className="w-[300px] max-w-full">
            <FieldLabel htmlFor="connect-link" className="sr-only">
              Connect link
            </FieldLabel>
            <div className="relative">
              <Input
                ref={inputRef}
                id="connect-link"
                name="connect-link"
                type={revealed ? "text" : "password"}
                placeholder="paste your connect link"
                autoComplete="current-password"
                autoFocus
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  setError("");
                }}
                className="px-9 text-center"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={() => setRevealed((shown) => !shown)}
                aria-label={
                  revealed ? "hide connect link" : "show connect link"
                }
                className="absolute inset-y-0 right-0.5 my-auto text-muted-foreground hover:bg-transparent hover:text-foreground"
              >
                {revealed ? <EyeOff /> : <Eye />}
              </Button>
            </div>
          </Field>

          <Button
            type="submit"
            disabled={busy}
            className="w-[180px] max-w-full"
          >
            {busy ? "connecting..." : "connect"}
          </Button>

          {isDesktopApp && selfHost && (
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
