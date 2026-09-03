import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { Field } from "@/components/ui/field";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import type { SettingDef } from "@/lib/voice";
import { DynamicSettings, CollapsibleChevronButton } from "./setting-controls";

export function UsageCollapsible({
  onOpen,
  children,
}: {
  onOpen: () => void;
  children: React.ReactNode;
}) {
  return (
    <Collapsible
      onOpenChange={(isOpen) => {
        if (isOpen) onOpen();
      }}
    >
      <CollapsibleChevronButton>usage</CollapsibleChevronButton>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  );
}

// --- Domain section ---

export function DomainSection({
  icon,
  title,
  configured,
  provider,
  enabled,
  onToggleEnabled,
  settings,
  domain,
  agentName,
  onSettingChange,
  usageContent,
}: {
  icon: React.ReactNode;
  title: string;
  configured: boolean;
  provider: string | null;
  enabled: boolean;
  onToggleEnabled: (v: boolean) => void;
  settings?: SettingDef[];
  domain: "stt" | "tts";
  agentName: string | null;
  onSettingChange: (settings: SettingDef[]) => void;
  usageContent: React.ReactNode;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          {icon}
          {title}
          {provider && (
            <span className="text-sm text-muted-foreground font-normal">
              {provider}
            </span>
          )}
        </CardTitle>
        {!configured && (
          <CardDescription className="text-warning">
            not configured, ask the agent to set it up
          </CardDescription>
        )}
        <CardAction>
          <Switch
            checked={enabled && configured}
            disabled={!configured}
            onCheckedChange={onToggleEnabled}
          />
        </CardAction>
      </CardHeader>
      {configured && enabled && (
        <CardContent>
          <Field orientation="vertical" className="gap-3">
            {usageContent}
            {settings && settings.length > 0 && (
              <DynamicSettings
                settings={settings}
                domain={domain}
                agentName={agentName}
                onSettingChange={onSettingChange}
              />
            )}
          </Field>
        </CardContent>
      )}
    </Card>
  );
}

// --- Dynamic settings renderer ---
