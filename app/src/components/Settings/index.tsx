import { useState } from "react";
import { Settings as SettingsIcon, Sun, Moon, Monitor, LogOut } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Separator } from "@/components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTheme, type Theme } from "@/stores/use-theme";
import { useAuth } from "@/providers/AuthProvider";
import { getConnection } from "@/lib/connection";
import { StatusPill } from "@/components/StatusPill";

export function Settings() {
  const [open, setOpen] = useState(false);
  const theme = useTheme((s) => s.theme);
  const setTheme = useTheme((s) => s.setTheme);
  const { reachable, disconnect } = useAuth();

  const hostname = (() => {
    const conn = getConnection();
    if (!conn) return "";
    try { return new URL(conn.url).hostname; } catch { return conn.url; }
  })();

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-sm" onClick={() => setOpen(true)}>
            <SettingsIcon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>settings</TooltipContent>
      </Tooltip>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Settings</DialogTitle>
            <DialogDescription className="sr-only">Application settings</DialogDescription>
          </DialogHeader>

          <Field orientation="vertical" className="sm:flex-row sm:items-center">
            <FieldLabel>Theme</FieldLabel>
            <ToggleGroup
              type="single"
              value={theme}
              onValueChange={(value) => { if (value) setTheme(value as Theme); }}
              variant="outline"
              spacing={2}
            >
              <ToggleGroupItem value="system"><Monitor /> System</ToggleGroupItem>
              <ToggleGroupItem value="light"><Sun /> Light</ToggleGroupItem>
              <ToggleGroupItem value="dark"><Moon /> Dark</ToggleGroupItem>
            </ToggleGroup>
          </Field>

          <Separator />

          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="flex-1 flex items-center gap-2 text-sm text-muted-foreground">
              <StatusPill showHostname={false} /> {reachable ? "Connected to" : "Cannot reach"} <span className="font-medium text-foreground">{hostname}</span>
            </div>
            <Button
              variant="outline"
              className="w-full sm:w-auto shrink-0"
              onClick={() => { setOpen(false); disconnect(); }}
            >
              <LogOut data-icon="inline-start" />
              Disconnect
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
