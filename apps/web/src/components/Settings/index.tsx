import { useState } from "react";
import {
  Settings as SettingsIcon,
  Sun,
  Moon,
  Monitor,
  LogOut,
  RefreshCw,
  CreditCard,
  ExternalLink,
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

// Hosted (managed) boxes are always under vesta.run; the account + billing page
// lives on the control plane. Self-hosted boxes never reach this.
const ACCOUNT_URL = "https://vesta.run/account";

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentSettingsSlot?: React.ReactNode;
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
  agentSettingsSlot,
}: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();
  const { disconnect } = useAuth();
  const {
    reachable,
    managed,
    gatewayVersion,
    gatewayBranch,
    gatewayChannel,
    gatewayAutoUpdate,
    updateAvailable,
    checkForUpdate,
  } = useGateway();
  const [checking, setChecking] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [channelSaving, setChannelSaving] = useState(false);
  const [autoUpdateSaving, setAutoUpdateSaving] = useState(false);

  // PUT a settings change, then re-check /version so the toggle reflects the
  // daemon's persisted value (and surfaces the matching update target). Switching
  // the channel never downgrades, so leaving beta only stops future betas.
  const saveSetting = async (
    setSaving: (value: boolean) => void,
    path: string,
    body: object,
    label: string,
  ) => {
    setSaving(true);
    try {
      await apiJson(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      await checkForUpdate();
    } catch (err) {
      console.warn(`[settings] failed to set ${label}:`, err);
    } finally {
      setSaving(false);
    }
  };

  const onToggleBeta = (enabled: boolean) =>
    saveSetting(
      setChannelSaving,
      "/settings/channel",
      { channel: enabled ? "beta" : "stable" },
      "release channel",
    );

  const onToggleAutoUpdate = (enabled: boolean) =>
    saveSetting(
      setAutoUpdateSaving,
      "/settings/auto-update",
      { auto_update: enabled },
      "auto-update",
    );

  const onCheckForUpdate = async () => {
    setChecking(true);
    try {
      await checkForUpdate();
    } finally {
      setChecking(false);
    }
  };
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
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription className="sr-only">
            Application settings
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {agentSettingsSlot && (
            <MenuSection title="Agent">
              <div onClick={() => onOpenChange(false)}>{agentSettingsSlot}</div>
            </MenuSection>
          )}

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

          <MenuSection title="Mode">
            <Field
              orientation="horizontal"
              className="items-center justify-between"
            >
              <FieldContent>
                <FieldLabel className="text-sm">level</FieldLabel>
                <FieldDescription>
                  simple hides advanced controls and shows curated views;
                  advanced exposes the full file tree, debug info, and more
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

          <MenuSection title="Connection">
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:flex-nowrap sm:items-center">
              <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                <StatusPill showHostname={false} />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="text-muted-foreground">
                    {reachable ? "Connected to" : "Cannot reach"}
                  </span>
                  <span className="min-w-0 truncate font-medium text-foreground">
                    {hostname}
                  </span>
                  {(gatewayVersion || gatewayBranch) && (
                    <span className="text-xs text-muted-foreground">
                      {gatewayVersion && <>gateway v{gatewayVersion}</>}
                      {gatewayVersion && gatewayBranch && " "}
                      {gatewayBranch && <>({gatewayBranch})</>}
                    </span>
                  )}
                  {reachable && (
                    <button
                      type="button"
                      onClick={onCheckForUpdate}
                      disabled={checking}
                      className="mt-1 inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      <RefreshCw
                        data-icon="inline-start"
                        className={checking ? "animate-spin" : undefined}
                      />
                      {updateAvailable
                        ? "Update available"
                        : checking
                          ? "Checking…"
                          : "Check for updates"}
                    </button>
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
            {reachable && managed && (
              <Button
                variant="secondary"
                className="mt-3 w-full justify-start"
                onClick={() => openExternalUrl(ACCOUNT_URL)}
              >
                <CreditCard data-icon="inline-start" />
                Manage account &amp; billing
                <ExternalLink data-icon="inline-end" className="ml-auto" />
              </Button>
            )}
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
        </div>
      </DialogContent>
      <GatewayLogsViewer open={showLogs} onOpenChange={setShowLogs} />
    </Dialog>
  );
}

export function Settings({
  agentSettingsSlot,
}: {
  agentSettingsSlot?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button variant="outline" size="icon-lg" onClick={() => setOpen(true)}>
        <SettingsIcon />
      </Button>
      <SettingsDialog
        open={open}
        onOpenChange={setOpen}
        agentSettingsSlot={agentSettingsSlot}
      />
    </>
  );
}
