import { LogOut } from "lucide-react";
import { Footer } from "@/components/Footer";
import { NavbarLogoText } from "@/components/Logo/LogoText";
import { Navbar } from "@/components/Navbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/providers/AuthProvider";
import { useAppUpdate } from "@/hooks/use-app-update";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";

// Terminal takeover shown when this app is older than the gateway's minimum supported client (the
// /sync hello's min_supported): the app fell below the served version window, and only the app
// updating resolves it, so the socket is terminal (no reconnect storm). The desktop app self-update
// is manual, so this screen carries the "update Vesta desktop" button that downloads and relaunches
// into the fix. Impossible in a browser by construction: vestad serves this exact bundle, so the
// client version equals the gateway version and is never below the window.
export function AppBehindScreen() {
  const { disconnect } = useAuth();
  const { supported, phase, percent, start, relaunch } = useAppUpdate();

  return (
    <>
      <Navbar center={<NavbarLogoText />} trailing={<StatusPill />} />
      <Empty>
        <EmptyHeader className="max-w-lg">
          <EmptyTitle>update required</EmptyTitle>
          <EmptyDescription>
            your app (v{__APP_VERSION__}) is too old for this gateway. update
            Vesta desktop to reconnect.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <div className="flex items-center gap-2">
            {supported &&
              (phase === "downloading" ? (
                <Button disabled>
                  <Spinner className="size-4" />
                  {Math.round(percent)}%
                </Button>
              ) : phase === "ready" ? (
                <Button
                  onClick={() => {
                    void relaunch();
                  }}
                >
                  relaunch to finish
                </Button>
              ) : (
                <Button
                  onClick={() => {
                    void start();
                  }}
                >
                  {phase === "error" ? "retry" : "update Vesta desktop"}
                </Button>
              ))}
            <Button
              variant="outline"
              size="icon"
              aria-label="disconnect"
              title="disconnect"
              onClick={() => disconnect()}
            >
              <LogOut />
            </Button>
          </div>
        </EmptyContent>
      </Empty>
      <Footer />
    </>
  );
}
