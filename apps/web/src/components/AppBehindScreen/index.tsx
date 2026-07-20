import { LogOut } from "lucide-react";
import { Footer } from "@/components/Footer";
import { LogoText } from "@/components/Logo/LogoText";
import { Navbar } from "@/components/Navbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/AuthProvider";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";

// Terminal takeover shown when this app is older than the gateway's minimum supported client (the
// /sync hello's min_supported): the app fell below the served version window, and only the app
// updating resolves it, so the socket is terminal (no reconnect storm). The desktop app already
// self-updates to the latest release in the background (applied on relaunch), which is what fixes
// this; the copy points there. Impossible in a browser by construction: vestad serves this exact
// bundle, so the client version equals the gateway version and is never below the window.
export function AppBehindScreen() {
  const { disconnect } = useAuth();

  return (
    <>
      <Navbar center={<LogoText />} trailing={<StatusPill />} />
      <Empty>
        <EmptyHeader className="max-w-lg">
          <EmptyTitle>update required</EmptyTitle>
          <EmptyDescription>
            your app (v{__APP_VERSION__}) is too old for this gateway. Vesta is
            updating in the background; quit and relaunch once it finishes.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="outline" onClick={() => disconnect()}>
            <LogOut data-icon="inline-start" />
            disconnect
          </Button>
        </EmptyContent>
      </Empty>
      <Footer />
    </>
  );
}
