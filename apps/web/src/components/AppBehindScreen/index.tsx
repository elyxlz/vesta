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

// Terminal takeover shown when the /sync handshake reports an incompatible protocol floor:
// the app and gateway support non-overlapping protocol ranges, so no socket can ever open.
// The desktop app self-updates to the latest release on its own (background, applied on the
// next relaunch) and the gateway is updated via the UpdatePill, so the only fix is to update
// one side; this just tells the user and offers a bail-out. Impossible in a browser by
// construction: vestad serves this exact bundle, so its protocol always matches.
export function IncompatibleScreen() {
  const { disconnect } = useAuth();

  return (
    <>
      <Navbar center={<LogoText />} trailing={<StatusPill />} />
      <Empty>
        <EmptyHeader className="max-w-lg">
          <EmptyTitle>incompatible version</EmptyTitle>
          <EmptyDescription>
            your app (v{__APP_VERSION__}) and your gateway speak different sync
            protocols. update the app or the gateway to reconnect.
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
