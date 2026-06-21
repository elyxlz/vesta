import { useEffect, useRef, useState } from "react";
import {
  Settings as SettingsIcon,
  Sun,
  Moon,
  Monitor,
  LogOut,
  RefreshCw,
  CreditCard,
  ExternalLink,
  SlidersHorizontal,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { MenuSection } from "@/components/ui/menu-section";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTheme } from "@/providers/ThemeProvider";
type Theme = "dark" | "light" | "system";
import { useAuth } from "@/providers/AuthProvider";
import { useTauri } from "@/providers/TauriProvider";
import { useGateway } from "@/providers/GatewayProvider";
import { getConnection } from "@/lib/connection";
import { apiJson } from "@/api/client";
import { StatusPill } from "@/components/StatusPill";
import { UpdatePill } from "@/components/UpdatePill";
import { GatewayLogsViewer } from "@/components/GatewayLogsViewer";
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
import { Card, CardContent } from "@/components/ui/card";
import { KeybindsCard } from "@/components/Settings/KeybindsSection";
import { ConnectionControls } from "@/components/ConnectionControls";

// Hosted (managed) boxes are always under vesta.run; the account + billing page
// lives on the control plane. Self-hosted boxes never reach this.
const ACCOUNT_URL = "https://vesta.run/account";

// Each settings group renders as a subtle card so the roomy desktop modal reads
// as deliberately tiled rather than a stretched-out single column.
const CARD = "gap-2.5 rounded-2xl bg-muted/50 p-4 ring-1 ring-border/50";

// How long the "already on latest" confirmation lingers after a manual check.
const LATEST_NOTICE_MS = 3000;

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentName?: string;
  onOpenAgentSettings?: () => void;
}

function ConnectionToggle({
  label,
  description,
  checked,
  disabled,
  onCheckedChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <Field
      orientation="horizontal"
      className="mt-3 items-center justify-between"
    >
      <FieldContent>
        <FieldLabel className="text-sm">{label}</FieldLabel>
        <FieldDescription>{description}</FieldDescription>
      </FieldContent>
      <Switch
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
      />
    </Field>
  );
}

export function SettingsDialog({
  open,
  onOpenChange,
  agentName,
  onOpenAgentSettings,
}: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();
  const { disconnect } = useAuth();
  const {
    reachable,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- TEMP-QA: unused while Account card is forced visible
    managed,
    gatewayVersion,
    gatewayBranch,
    gatewayChannel,
    gatewayAutoUpdate,
    updateAvailable,
    checkForUpdate,
  } = useGateway();
  const [checking, setChecking] = useState(false);
  const [onLatest, setOnLatest] = useState(false);
  const latestNoticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const [channelSaving, setChannelSaving] = useState(false);
  const [autoUpdateSaving, setAutoUpdateSaving] = useState(false);

  const onToggleBeta = async (enabled: boolean) => {
    setChannelSaving(true);
    try {
      await apiJson("/settings/channel", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: enabled ? "beta" : "stable" }),
      });
      // Re-check so /version reflects the new channel (and surfaces the matching
      // version to update to). Switching channel never downgrades, so leaving beta
      // only stops future betas until stable catches up.
      await checkForUpdate();
    } catch (err) {
      console.warn("[settings] failed to set release channel:", err);
    } finally {
      setChannelSaving(false);
    }
  };

  const onToggleAutoUpdate = async (enabled: boolean) => {
    setAutoUpdateSaving(true);
    try {
      await apiJson("/settings/auto-update", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_update: enabled }),
      });
      // Re-read so the toggle reflects the daemon's persisted value.
      await checkForUpdate();
    } catch (err) {
      console.warn("[settings] failed to set auto-update:", err);
    } finally {
      setAutoUpdateSaving(false);
    }
  };

  const onCheckForUpdate = async () => {
    if (latestNoticeTimer.current) clearTimeout(latestNoticeTimer.current);
    setOnLatest(false);
    setChecking(true);
    try {
      await checkForUpdate();
      // If a newer version exists the header swaps to the UpdatePill, so this
      // confirmation only ever surfaces when we're already up to date.
      setOnLatest(true);
      latestNoticeTimer.current = setTimeout(
        () => setOnLatest(false),
        LATEST_NOTICE_MS,
      );
    } finally {
      setChecking(false);
    }
  };

  useEffect(
    () => () => {
      if (latestNoticeTimer.current) clearTimeout(latestNoticeTimer.current);
    },
    [],
  );
  const { isTauri } = useTauri();
  const naturalPacing = useChatPacing((s) => s.natural);
  const setNaturalPacing = useChatPacing((s) => s.setNatural);
  const appMode = useAppMode((s) => s.mode);
  const setAppMode = useAppMode((s) => s.setMode);

  const hostname = (() => {
    const conn = getConnection();
    if (!conn) return "";
    try {
      return new URL(conn.url).hostname;
    } catch {
      return conn.url;
    }
  })();

  return (
    <Dialog drawerOnMobile open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:flex md:h-[70vh] md:max-h-[70vh] md:w-[70vw] md:max-w-[70vw] md:flex-col md:pb-0">
        <DialogHeader className="flex-row items-center justify-between gap-2">
          <div className="flex flex-col gap-1.5">
            <DialogTitle className="md:text-lg">Settings</DialogTitle>
            <DialogDescription className="sr-only">
              Application settings
            </DialogDescription>
          </div>
          {reachable &&
            (updateAvailable ? (
              <UpdatePill className="shrink-0 md:absolute md:top-4 md:right-14 md:h-8" />
            ) : (
              <Button
                type="button"
                variant="ghost"
                size="xs"
                onClick={onCheckForUpdate}
                disabled={checking}
                className="text-muted-foreground md:absolute md:top-4 md:right-14 md:h-8"
              >
                {!onLatest && (
                  <RefreshCw
                    data-icon="inline-start"
                    className={`size-3.5 ${checking ? "animate-spin" : ""}`}
                  />
                )}
                {checking
                  ? "Checking…"
                  : onLatest
                    ? "On latest version already"
                    : "Check for updates"}
              </Button>
            ))}
        </DialogHeader>

        <div className="grid grid-cols-1 gap-4 md:-mr-3 md:min-h-0 md:flex-1 md:auto-rows-min md:grid-cols-2 md:content-start md:overflow-y-auto md:pr-3 md:pb-6">
          {agentName && onOpenAgentSettings && (
            <MenuSection title="Agent" className={CARD}>
              <Button
                variant="default"
                className="w-full justify-start"
                onClick={() => {
                  onOpenChange(false);
                  onOpenAgentSettings();
                }}
              >
                <SlidersHorizontal data-icon="inline-start" />
                {agentName}'s settings
              </Button>
            </MenuSection>
          )}

          <MenuSection title="Appearance" className={CARD}>
            <ToggleGroup
              type="single"
              value={theme}
              onValueChange={(value) => {
                if (value) setTheme(value as Theme);
              }}
              variant="outline"
              spacing={2}
            >
              {!isTauri && (
                <ToggleGroupItem value="system">
                  <Monitor /> System
                </ToggleGroupItem>
              )}
              <ToggleGroupItem value="light">
                <Sun /> Light
              </ToggleGroupItem>
              <ToggleGroupItem value="dark">
                <Moon /> Dark
              </ToggleGroupItem>
            </ToggleGroup>
          </MenuSection>

          <MenuSection title="Chat" className={CARD}>
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

          <MenuSection title="App" className={CARD}>
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

          <MenuSection title="Gateway" className={`${CARD} md:col-span-2`}>
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:flex-nowrap sm:items-center">
              <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                <StatusPill showHostname={false} />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="flex min-w-0 items-baseline gap-1">
                    <span className="shrink-0 text-muted-foreground">
                      {reachable ? "Connected to" : "Cannot reach"}
                    </span>
                    <span className="min-w-0 truncate font-medium text-foreground">
                      {hostname}
                    </span>
                  </span>
                  {(gatewayVersion || gatewayBranch) && (
                    <span className="text-xs text-muted-foreground">
                      {gatewayVersion && <>gateway v{gatewayVersion}</>}
                      {gatewayVersion && gatewayBranch && " "}
                      {gatewayBranch && <>({gatewayBranch})</>}
                    </span>
                  )}
                </div>
              </div>
              <Button
                variant="destructive"
                className="w-full shrink-0 whitespace-nowrap sm:w-auto"
                onClick={() => {
                  onOpenChange(false);
                  disconnect();
                }}
              >
                <LogOut data-icon="inline-start" />
                Disconnect
              </Button>
            </div>
            {reachable && (
              <ConnectionToggle
                label="beta releases"
                description="receive prereleases first to test them before everyone else; switching off stops future betas (it never downgrades)"
                checked={gatewayChannel === "beta"}
                disabled={channelSaving}
                onCheckedChange={onToggleBeta}
              />
            )}
            {reachable && (
              <ConnectionToggle
                label="automatic updates"
                description="apply new releases automatically in the background; switching off keeps you on the current version until you update manually"
                checked={gatewayAutoUpdate}
                disabled={autoUpdateSaving}
                onCheckedChange={onToggleAutoUpdate}
              />
            )}
          </MenuSection>

          {/* TEMP-QA: dropped `&& managed` to QA the Account card; restore `reachable && managed &&` */}
          {reachable && (
            <MenuSection title="Account" className={CARD}>
              <Button
                variant="outline"
                className="w-full justify-start"
                onClick={() => openExternalUrl(ACCOUNT_URL)}
              >
                <CreditCard data-icon="inline-start" />
                Manage account &amp; billing
                <ExternalLink data-icon="inline-end" className="ml-auto" />
              </Button>
            </MenuSection>
          )}
        </div>
      </DialogContent>
      <GatewayLogsViewer open={showLogs} onOpenChange={setShowLogs} />
    </Dialog>
  );
}

// The app-level settings surface, rendered as a page at /settings. App/client +
// box concerns only — per-agent config lives at /agent/:name/settings.
export function AppSettings() {
  const { theme, setTheme } = useTheme();
  const { isTauri } = useTauri();
  const { disconnect } = useAuth();
  const { reachable, managed, gatewayVersion, gatewayBranch } = useGateway();
  const naturalPacing = useChatPacing((s) => s.natural);
  const setNaturalPacing = useChatPacing((s) => s.setNatural);
  const appMode = useAppMode((s) => s.mode);
  const setAppMode = useAppMode((s) => s.setMode);

  const hostname = (() => {
    const conn = getConnection();
    if (!conn) return "";
    try {
      return new URL(conn.url).hostname;
    } catch {
      return conn.url;
    }
  })();

  return (
    <div className="mx-auto grid w-full max-w-3xl grid-cols-1 gap-4 md:auto-rows-min md:grid-cols-2">
      <Card size="sm">
        <CardContent>
          <MenuSection title="Appearance">
            <ToggleGroup
              type="single"
              value={theme}
              onValueChange={(value) => {
                if (value) setTheme(value as Theme);
              }}
              variant="outline"
              spacing={2}
            >
              {!isTauri && (
                <ToggleGroupItem value="system">
                  <Monitor /> System
                </ToggleGroupItem>
              )}
              <ToggleGroupItem value="light">
                <Sun /> Light
              </ToggleGroupItem>
              <ToggleGroupItem value="dark">
                <Moon /> Dark
              </ToggleGroupItem>
            </ToggleGroup>
          </MenuSection>
        </CardContent>
      </Card>

      <Card size="sm">
        <CardContent>
          <MenuSection title="Chat">
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
          <MenuSection title="App">
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
          <MenuSection title="Gateway">
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:flex-nowrap sm:items-center">
              <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                <StatusPill showHostname={false} />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="flex min-w-0 items-baseline gap-1">
                    <span className="shrink-0 text-muted-foreground">
                      {reachable ? "Connected to" : "Cannot reach"}
                    </span>
                    <span className="min-w-0 truncate font-medium text-foreground">
                      {hostname}
                    </span>
                  </span>
                  {(gatewayVersion || gatewayBranch) && (
                    <span className="text-xs text-muted-foreground">
                      {gatewayVersion && <>gateway v{gatewayVersion}</>}
                      {gatewayVersion && gatewayBranch && " "}
                      {gatewayBranch && <>({gatewayBranch})</>}
                    </span>
                  )}
                </div>
              </div>
              <Button
                variant="destructive"
                className="w-full shrink-0 whitespace-nowrap sm:w-auto"
                onClick={() => disconnect()}
              >
                <LogOut data-icon="inline-start" />
                Disconnect
              </Button>
            </div>
            <ConnectionControls />
          </MenuSection>
        </CardContent>
      </Card>

      {reachable && managed && (
        <Card size="sm">
          <CardContent>
            <MenuSection title="Account">
              <Button
                variant="outline"
                className="w-full justify-start"
                onClick={() => openExternalUrl(ACCOUNT_URL)}
              >
                <CreditCard data-icon="inline-start" />
                Manage account &amp; billing
                <ExternalLink data-icon="inline-end" className="ml-auto" />
              </Button>
            </MenuSection>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// The gear button that owns its open state and pops the SettingsDialog. Used
// where settings is reached via a standalone icon (navbar, version-mismatch
// prompt); AgentMenu drives SettingsDialog directly with its own trigger.
export function SettingsButton() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button variant="outline" size="icon-lg" onClick={() => setOpen(true)}>
        <SettingsIcon />
      </Button>
      <SettingsDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
