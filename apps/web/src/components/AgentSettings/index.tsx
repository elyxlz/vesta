import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SettingsScrollArea } from "@/components/SettingsScrollArea";
import { ActionsCard } from "./ActionsCard";
import { NotificationInterruptRulesCard } from "./NotificationInterruptRulesCard";
import { NotificationsCard } from "./NotificationsCard";
import { FilesTab } from "./FilesTab";
import { LogsTab } from "./LogsTab";
import { ProviderCard } from "./ProviderCard";
import { SttCard, TtsCard } from "./VoiceSection";

export function AgentSettings() {
  return (
    <Tabs
      defaultValue="general"
      className="flex min-h-0 w-full flex-1 flex-col gap-4 pt-4"
    >
      <TabsList className="shrink-0 self-center">
        <TabsTrigger value="general">general</TabsTrigger>
        <TabsTrigger value="notifications">notifications</TabsTrigger>
        <TabsTrigger value="files">files</TabsTrigger>
        <TabsTrigger value="logs">logs</TabsTrigger>
      </TabsList>

      <SettingsScrollArea>
        <TabsContent value="general">
          <div className="mx-auto grid w-full max-w-5xl gap-4 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
            <div className="flex flex-col gap-4 lg:sticky lg:top-0">
              <ActionsCard />
            </div>
            <div className="flex min-w-0 flex-col gap-4">
              <ProviderCard />
              <SttCard />
              <TtsCard />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="notifications">
          {/* Bento: a compact rules card beside the wider history it acts on. */}
          <div className="mx-auto grid max-w-7xl gap-4 xl:grid-cols-[24rem_minmax(0,1fr)] xl:items-start">
            <div className="flex flex-col gap-4 xl:sticky xl:top-0">
              <NotificationInterruptRulesCard />
            </div>
            <NotificationsCard />
          </div>
        </TabsContent>

        <TabsContent value="files">
          <div className="mx-auto w-full max-w-6xl">
            <FilesTab />
          </div>
        </TabsContent>

        <TabsContent value="logs">
          <div className="mx-auto w-full max-w-6xl">
            <LogsTab />
          </div>
        </TabsContent>
      </SettingsScrollArea>
    </Tabs>
  );
}
