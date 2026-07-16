import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings as SettingsIcon,
  Sun,
  Moon,
  Monitor,
  LogOut,
  CreditCard,
  ExternalLink,
  ScrollText,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { MenuSection } from "@/components/ui/menu-section";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTheme } from "@/providers/ThemeProvider";
type Theme = "dark" | "light" | "system";
import { useAuth } from "@/providers/AuthProvider";
import { useRuntime } from "@/providers/RuntimeProvider";
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
import { useAppMode, type AppMode } from "@/stores/use-app-mode";
import { openExternalUrl } from "@/lib/open-external-url";
import { KeybindsCard } from "@/components/Settings/KeybindsSection";
import { ConnectionControls } from "@/components/ConnectionControls";
import { useGatewaySetup } from "@/components/Settings/use-gateway-setup";
import { GatewayLogsViewer } from "@/components/GatewayLogsViewer";

// Hosted (managed) boxes are always under vesta.run; the account + billing page
// lives on the control plane. Self-hosted boxes never reach this.
const ACCOUNT_URL = "https://vesta.run/account";

// The app-level settings surface, rendered as a page at /settings. App/client +
// box concerns only — per-agent config lives at /agent/:name/settings.
export function AppSettings() {
  const { theme, setTheme } = useTheme();
  const { isDesktopApp } = useRuntime();
  const { disconnect } = useAuth();
  const { reachable, managed, gatewayVersion, gatewayBranch } = useGateway();
  const naturalPacing = useChatPacing((s) => s.natural);
  const setNaturalPacing = useChatPacing((s) => s.setNatural);
  const appMode = useAppMode((s) => s.mode);
  const setAppMode = useAppMode((s) => s.setMode);
  const hostname = connectionHostname();
  const gatewaySetup = useGatewaySetup();
  const [showLogs, setShowLogs] = useState(false);

  return (
    <div className="mx-auto mt-4 grid w-full max-w-5xl grid-cols-1 gap-4 pb-6 md:auto-rows-min md:grid-cols-2">
      <Card size="sm">
        <CardContent>
          <MenuSection title="appearance">
            <ToggleGroup
              type="single"
              value={theme}
              onValueChange={(value) => {
                if (value) setTheme(value as Theme);
              }}
              variant="outline"
              spacing={2}
            >
              {!isDesktopApp && (
                <ToggleGroupItem value="system">
                  <Monitor /> system
                </ToggleGroupItem>
              )}
              <ToggleGroupItem value="light">
                <Sun /> light
              </ToggleGroupItem>
              <ToggleGroupItem value="dark">
                <Moon /> dark
              </ToggleGroupItem>
            </ToggleGroup>
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
                <FieldLabel className="text-sm">natural pacing</FieldLabel>
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

      <Card size="sm">
        <CardContent>
          <MenuSection title="app">
            <Field
              orientation="horizontal"
              className="items-center justify-between"
            >
              <FieldContent>
                <FieldLabel className="text-sm">detail level</FieldLabel>
                <FieldDescription>
                  simple keeps the interface focused with curated views;
                  advanced reveals the full set of controls and detail
                </FieldDescription>
              </FieldContent>
              <ToggleGroup
                type="single"
                value={appMode}
                onValueChange={(value) => {
                  if (value) setAppMode(value as AppMode);
                }}
                variant="outline"
                spacing={2}
              >
                <ToggleGroupItem value="simple">simple</ToggleGroupItem>
                <ToggleGroupItem value="advanced">advanced</ToggleGroupItem>
              </ToggleGroup>
            </Field>
          </MenuSection>
        </CardContent>
      </Card>

      <KeybindsCard />

      <Card size="sm" className="md:col-span-2">
        <CardContent>
          <MenuSection
            title="gateway"
            trailing={
              (gatewayVersion || gatewayBranch) && (
                <span className="shrink-0 text-xs font-medium text-muted-foreground">
                  {gatewayVersion && <>v{gatewayVersion}</>}
                  {gatewayVersion && gatewayBranch && " "}
                  {gatewayBranch && <>({gatewayBranch})</>}
                </span>
              )
            }
          >
            <div className="mt-2 flex min-w-0 flex-col gap-3 sm:flex-row sm:flex-nowrap sm:items-center">
              <div className="flex min-w-0 flex-1 items-center gap-2 text-sm leading-none">
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
              <Button
                variant="destructive"
                className="w-full shrink-0 whitespace-nowrap sm:w-auto"
                onClick={() => disconnect()}
              >
                <LogOut data-icon="inline-start" />
                disconnect
              </Button>
            </div>
            <ConnectionControls />
            {gatewaySetup && (
              <div className="mt-4 flex flex-col gap-3">
                <Field
                  orientation="horizontal"
                  className="items-center justify-between"
                >
                  <FieldContent>
                    <FieldLabel className="text-sm">lan access</FieldLabel>
                    <FieldDescription>
                      whether other devices on your network can reach this
                      gateway
                    </FieldDescription>
                  </FieldContent>
                  <span className="shrink-0 text-sm text-muted-foreground">
                    {gatewaySetup.info.lan.exposed
                      ? (gatewaySetup.info.lan.url ?? "enabled")
                      : "disabled"}
                  </span>
                </Field>
                <Field
                  orientation="horizontal"
                  className="items-center justify-between"
                >
                  <FieldContent>
                    <FieldLabel className="text-sm">remote access</FieldLabel>
                    <FieldDescription>
                      secure tunnel address for reaching this gateway from
                      anywhere
                    </FieldDescription>
                  </FieldContent>
                  <span className="min-w-0 shrink-0 truncate text-sm text-muted-foreground">
                    {gatewaySetup.info.tunnel_url ?? "not set"}
                  </span>
                </Field>
                <Field
                  orientation="horizontal"
                  className="items-center justify-between"
                >
                  <FieldContent>
                    <FieldLabel className="text-sm">backups</FieldLabel>
                    <FieldDescription>
                      automatic nightly snapshots of your agents
                    </FieldDescription>
                  </FieldContent>
                  <span className="shrink-0 text-sm text-muted-foreground">
                    {gatewaySetup.settings.auto_backup.enabled
                      ? `daily at ${String(gatewaySetup.settings.auto_backup.hour).padStart(2, "0")}:00 server time`
                      : "disabled"}
                  </span>
                </Field>
              </div>
            )}
          </MenuSection>
        </CardContent>
      </Card>

      <GatewayLogsViewer open={showLogs} onOpenChange={setShowLogs} />

      {reachable && managed && (
        <Card size="sm">
          <CardContent>
            <MenuSection title="account">
              <Button
                variant="outline"
                className="w-full justify-start"
                onClick={() => openExternalUrl(ACCOUNT_URL)}
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

// The gear button. Navigates to the app settings page.
export function SettingsButton() {
  const navigate = useNavigate();

  return (
    <Button
      variant="outline"
      size="icon-lg"
      aria-label="settings"
      onClick={() => navigate("/settings")}
    >
      <SettingsIcon />
    </Button>
  );
}
