import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { native } from "@/lib/native";
import { useCredentialStorage } from "@/stores/use-credential-storage";

// Where the gateway sign-in lives on this device, shown only when something is wrong with it: the
// desktop store fell back to Electron's unprotected Linux backend (once per install, dismissible),
// or the last write of the connection failed (until a write succeeds).
export function CredentialStorageCard() {
  const secureProbe = native.credentialStorageIsSecure;
  const [insecure, setInsecure] = useState(false);
  const writeError = useCredentialStorage((s) => s.writeError);
  const insecureDismissed = useCredentialStorage((s) => s.insecureDismissed);
  const dismissInsecure = useCredentialStorage((s) => s.dismissInsecure);

  useEffect(() => {
    if (!secureProbe) return;
    void secureProbe().then((secure) => {
      setInsecure(!secure);
    });
  }, [secureProbe]);

  const showInsecure = insecure && !insecureDismissed;
  if (!showInsecure && writeError === null) return null;

  return (
    <div className="flex flex-col gap-3 md:col-span-2">
      {writeError !== null && (
        <Alert variant="destructive">
          <ShieldAlert />
          <AlertTitle>your sign-in could not be saved</AlertTitle>
          <AlertDescription>
            {writeError}. You stay connected now, and you will sign in again at
            the next launch.
          </AlertDescription>
        </Alert>
      )}
      {showInsecure && (
        <Alert variant="warning">
          <ShieldAlert />
          <AlertTitle>your sign-in is stored without OS protection</AlertTitle>
          <AlertDescription>
            this system has no secret service (GNOME Keyring or KWallet), so the
            gateway tokens are kept in a file any local program can read.
            install one to protect them.
          </AlertDescription>
          <AlertAction>
            <Button variant="ghost" size="xs" onClick={dismissInsecure}>
              got it
            </Button>
          </AlertAction>
        </Alert>
      )}
    </div>
  );
}
