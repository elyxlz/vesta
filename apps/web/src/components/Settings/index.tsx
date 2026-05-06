import { useState } from "react";
import {
  Settings as SettingsIcon,
  Sun,
  Moon,
  Monitor,
  LogOut,
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

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentSettingsSlot?: React.ReactNode;
}

export function SettingsDialog({
  open,
  onOpenChange,
  agentSettingsSlot,
}: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();
  const { disconnect } = useAuth();
  const { reachable, gatewayVersion, gatewayBranch } = useGateway();
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
          </MenuSection>
        </div>
      </DialogContent>
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
