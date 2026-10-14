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
import type { VoiceDomain } from "@vesta/core";
import type { SettingDef } from "@/lib/voice";
import { CollapsibleChevronButton } from "./collapsible-chevron-button";
import { DynamicSettings, OptionList } from "./setting-controls";

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
  description,
  configured,
  provider,
  connected,
  onUseProvider,
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
  // What the role does, for a role that is not self-evident. A role with none shows a
  // warning while it is not configured.
  description?: string;
  configured: boolean;
  provider: string | null;
  // The providers connected to this role. With two or more, the card offers the switch.
  connected: string[];
  onUseProvider: (provider: string) => void;
  enabled: boolean;
  onToggleEnabled: (v: boolean) => void;
  settings?: SettingDef[];
  domain: VoiceDomain;
  agentName: string | null;
  onSettingChange: (settings: SettingDef[]) => void;
  usageContent: React.ReactNode;
}) {
  const hasSettings = (settings?.length ?? 0) > 0;
  const hasContent =
    connected.length > 1 || Boolean(usageContent) || hasSettings;
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
        {description ? (
          <CardDescription>{description}</CardDescription>
        ) : (
          !configured && (
            <CardDescription className="text-warning">
              not configured, ask the agent to set it up
            </CardDescription>
          )
        )}
        <CardAction>
          <Switch
            checked={enabled && configured}
            disabled={!configured}
            onCheckedChange={onToggleEnabled}
          />
        </CardAction>
      </CardHeader>
      {configured && enabled && hasContent && (
        <CardContent>
          <Field orientation="vertical" className="gap-3">
            {connected.length > 1 && (
              <OptionList
                label="provider"
                selected={provider}
                options={connected.map((name) => ({
                  value: name,
                  label: name,
                }))}
                onChange={onUseProvider}
              />
            )}
            {usageContent}
            {settings && hasSettings && (
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
