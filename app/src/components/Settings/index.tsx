import { useState } from "react";
import {
  Settings as SettingsIcon,
  Sun,
  Moon,
  Monitor,
  LogOut,
  SlidersHorizontal,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTheme } from "@/providers/ThemeProvider";
type Theme = "dark" | "light" | "system";
import { useAuth } from "@/providers/AuthProvider";
import { getConnection } from "@/lib/connection";
import { StatusPill } from "@/components/StatusPill";

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const navigate = useNavigate();
  const { name: activeAgentName } = useParams<{ name?: string }>();
  const { theme, setTheme } = useTheme();
  const { reachable, disconnect } = useAuth();

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

        {activeAgentName && (
          <>
            <Button
              variant="default"
              className="w-full justify-start"
              onClick={() => {
                onOpenChange(false);
                navigate(
                  `/agent/${encodeURIComponent(activeAgentName)}/settings`,
                );
              }}
            >
              <SlidersHorizontal data-icon="inline-start" />
              {activeAgentName}'s settings
            </Button>
          </>
        )}

        <Field orientation="vertical" className="sm:flex-row sm:items-center">
          <FieldLabel>Theme</FieldLabel>
          <ToggleGroup
            type="single"
            value={theme}
            onValueChange={(value) => {
              if (value) setTheme(value as Theme);
            }}
            variant="outline"
            spacing={2}
          >
            <ToggleGroupItem value="system">
              <Monitor /> System
            </ToggleGroupItem>
            <ToggleGroupItem value="light">
              <Sun /> Light
            </ToggleGroupItem>
            <ToggleGroupItem value="dark">
              <Moon /> Dark
            </ToggleGroupItem>
          </ToggleGroup>
        </Field>

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
      </DialogContent>
    </Dialog>
  );
}

export function Settings() {
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
