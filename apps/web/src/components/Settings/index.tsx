import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings as SettingsIcon,
  LogOut,
  CreditCard,
  ExternalLink,
  ScrollText,
  ArrowLeftRight,
} from "lucide-react";
import { AppearancePicker } from "@/components/Settings/AppearancePicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { MenuSection } from "@/components/ui/menu-section";
import { useTheme } from "@/providers/ThemeProvider";
import { useAuth } from "@/providers/AuthProvider";
import { useGateway } from "@/providers/GatewayProvider";
import { connectionHostname } from "@/lib/connection";
import { StatusPill } from "@/components/StatusPill";
import { Switch } from "@/components/ui/switch";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { useChatPacing } from "@/stores/use-chat-pacing";
import { useSwitchGateway } from "@/stores/use-switch-gateway";
import { openExternalUrl } from "@/lib/open-external-url";
import { KeybindsCard } from "@/components/Settings/KeybindsSection";
import { DevicesCard } from "@/components/Settings/DevicesCard";
import { UpdatesCard } from "@/components/Settings/UpdatesCard";
import { ConnectionControls } from "@/components/ConnectionControls";
import { GatewayRestart } from "@/components/GatewayRestart";
import {
  useGatewaySetup,
  type GatewaySetup,
} from "@/components/Settings/use-gateway-setup";
import { GatewayLogsViewer } from "@/components/GatewayLogsViewer";

// Hosted (managed) boxes are always under vesta.run; the account + billing page
// lives on the control plane. Self-hosted boxes never reach this.
const ACCOUNT_URL = "https://vesta.run/account";

// The app-level settings surface, rendered as a page at /settings. App/client +
// box concerns only — per-agent config lives at /agent/:name/settings.
export function AppSettings() {
  const { theme, setTheme } = useTheme();
  const { disconnect } = useAuth();
  const { reachable, managed, gatewayVersion } = useGateway();
  const naturalPacing = useChatPacing((s) => s.natural);
  const setNaturalPacing = useChatPacing((s) => s.setNatural);
  const hostname = connectionHostname();
  const gatewaySetup = useGatewaySetup();
  const openSwitchGateway = useSwitchGateway((s) => s.setOpen);
  const [showLogs, setShowLogs] = useState(false);

  return (
    <div className="mx-auto mt-4 grid w-full max-w-[53rem] grid-cols-1 gap-4 pb-6 md:auto-rows-min md:grid-cols-2">
      <Card size="sm">
        <CardContent>
          <MenuSection title="appearance">
            <AppearancePicker value={theme} onChange={setTheme} />
          </MenuSection>
        </CardContent>
      </Card>

      <Card size="sm">
        <CardContent>
          <MenuSection title="chat">
            <Field
              orientation="horizontal"
              className="items-center justify-between"
            >
              <FieldContent>
                <FieldLabel className="text-base">natural pacing</FieldLabel>
                <FieldDescription>
                  simulate typing delay before assistant messages appear
                </FieldDescription>
              </FieldContent>
              <Switch
                checked={naturalPacing}
                onCheckedChange={setNaturalPacing}
              />
            </Field>
          </MenuSection>
        </CardContent>
      </Card>

      <KeybindsCard />

      <UpdatesCard />

      <Card size="sm" className="md:col-span-2">
        <CardContent>
          <MenuSection
            title="gateway"
            trailing={
              gatewayVersion && (
                <span className="shrink-0 text-sm font-medium text-muted-foreground">
                  v{gatewayVersion}
                </span>
              )
            }
          >
            <div className="mt-2 flex flex-col gap-3">
              <div className="flex min-w-0 items-center gap-2 text-base leading-none">
                <StatusPill showHostname={false} />
                <span className="flex min-w-0 flex-1 items-baseline gap-1">
                  <span className="shrink-0 text-muted-foreground">
                    {reachable ? "connected to" : "can't reach"}
                  </span>
                  <span className="min-w-0 truncate font-medium text-foreground">
                    {hostname}
                  </span>
                </span>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
                {reachable && (
                  <Button
                    variant="outline"
                    className="w-full shrink-0 whitespace-nowrap sm:w-auto"
                    onClick={() => setShowLogs(true)}
                  >
                    <ScrollText data-icon="inline-start" />
                    view logs
                  </Button>
                )}
                {reachable && <GatewayRestart />}
                <Button
                  variant="outline"
                  className="w-full shrink-0 whitespace-nowrap sm:w-auto"
                  onClick={() => openSwitchGateway(true)}
                >
                  <ArrowLeftRight data-icon="inline-start" />
                  switch gateway
                </Button>
                <Button
                  variant="destructive"
                  className="w-full shrink-0 whitespace-nowrap sm:w-auto"
                  onClick={() => disconnect()}
                >
                  <LogOut data-icon="inline-start" />
                  disconnect
                </Button>
              </div>
            </div>
            <ConnectionControls />
            {gatewaySetup && <GatewaySetupFields setup={gatewaySetup} />}
          </MenuSection>
        </CardContent>
      </Card>

      <DevicesCard />

      <GatewayLogsViewer open={showLogs} onOpenChange={setShowLogs} />

      {reachable && managed && (
        <Card size="sm">
          <CardContent>
            <MenuSection title="account">
              <Button
                variant="outline"
                className="w-full justify-start"
                onClick={() => {
                  void openExternalUrl(ACCOUNT_URL);
                }}
              >
                <CreditCard data-icon="inline-start" />
                manage account &amp; billing
                <ExternalLink data-icon="inline-end" className="ml-auto" />
              </Button>
            </MenuSection>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// The read-only daemon setup rows (lan, tunnel) of the gateway card.
function GatewaySetupFields({ setup }: { setup: GatewaySetup }) {
  return (
    <div className="mt-4 flex flex-col gap-3">
      <Field orientation="horizontal" className="items-center justify-between">
        <FieldContent>
          <FieldLabel className="text-base">lan access</FieldLabel>
          <FieldDescription>
            whether other devices on your network can reach this gateway
          </FieldDescription>
        </FieldContent>
        <span className="shrink-0 text-base text-muted-foreground">
          {setup.info.lan.exposed
            ? (setup.info.lan.url ?? "enabled")
            : "disabled"}
        </span>
      </Field>
      <Field orientation="horizontal" className="items-center justify-between">
        <FieldContent>
          <FieldLabel className="text-base">remote access</FieldLabel>
          <FieldDescription>
            secure tunnel address for reaching this gateway from anywhere
          </FieldDescription>
        </FieldContent>
        <span className="min-w-0 shrink-0 truncate text-base text-muted-foreground">
          {setup.info.tunnel_url ?? "not set"}
        </span>
      </Field>
    </div>
  );
}

// The gear button. Navigates to the app settings page.
export function SettingsButton() {
  const navigate = useNavigate();

  return (
    <Button
      variant="outline"
      size="icon-lg"
      aria-label="settings"
      onClick={() => {
        void navigate("/settings");
      }}
    >
      <SettingsIcon />
    </Button>
  );
}
