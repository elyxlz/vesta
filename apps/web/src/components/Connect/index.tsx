import { useRef, useState } from "react";
import { useResource } from "@vesta/core/react";
import { Navigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Eye, EyeOff, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel, FieldDescription } from "@/components/ui/field";
import { LogoText } from "@/components/Logo/LogoText";
import { fade } from "@/lib/motion";
import { errorMessage } from "@/lib/utils";
import { Navbar } from "@/components/Navbar";
import { parseConnectLink } from "@/lib/connection";
import { readRecentGateways } from "@/lib/recent-gateways";
import { useAuth } from "@/providers/AuthProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { GetAppsRow } from "@/components/GetApps";

// VITE_VESTAD_HOSTED=true means the SPA was bundled by vestad itself, so
// window.location.origin already points at the right vestad instance.
// Anything else (the desktop app, vite dev, or self-hosted on a non-vestad
// server) needs the user to enter the vestad host explicitly.
const needHostInput = import.meta.env.VITE_VESTAD_HOSTED !== "true";

// A soft rise-and-fade so the connect card settles in rather than snapping on.
const connectEntrance = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.3, ease: "easeOut" },
} as const;

function RecentGatewaysButton({
  onClick,
  visible,
}: {
  onClick: () => void;
  visible: boolean;
}) {
  if (!visible) return null;
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={onClick}
      className="text-xs text-muted-foreground"
    >
      <History />
      recent gateways
    </Button>
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

// Re-read each time the switch dialog closes, since it can forget a gateway.
function useHasRecentGateways(dialogOpen: boolean): boolean {
  const [closes, setCloses] = useState(0);
  const [wasOpen, setWasOpen] = useState(dialogOpen);
  if (wasOpen !== dialogOpen) {
    setWasOpen(dialogOpen);
    if (!dialogOpen) setCloses((count) => count + 1);
  }
  const saved = useResource(
    `recent-gateways-${String(closes)}`,
    readRecentGateways,
  );
  return saved.error === null && (saved.data?.length ?? 0) > 0;
}

export function Connect() {
  const { connected, connect, sessionExpired } = useAuth();
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const switchGatewayOpen = useDialogs((state) => state.open.switchGateway);
  const setDialogOpen = useDialogs((state) => state.setOpen);
  const setSwitchGatewayOpen = (open: boolean) => {
    setDialogOpen("switchGateway", open);
  };
  const hasRecentGateways = useHasRecentGateways(switchGatewayOpen);
  const inputRef = useRef<HTMLInputElement>(null);

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

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center">
      <Navbar />
      <div className="flex h-full w-full flex-col p-page">
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

            <RecentGatewaysButton
              visible={hasRecentGateways}
              onClick={() => setSwitchGatewayOpen(true)}
            />

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
        <GetAppsRow />
      </div>
    </div>
  );
}
