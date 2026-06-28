import { useRef } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLayout } from "@/stores/use-layout";
import { ActionsCard } from "./ActionsCard";
import {
  NotificationInterruptRulesCard,
  type NotificationInterruptRulesHandle,
} from "./NotificationInterruptRulesCard";
import { NotificationsCard } from "./NotificationsCard";
import { DefaultRulesCard } from "./DefaultRulesCard";
import { FilesTab } from "./FilesTab";
import { ProviderCard } from "./ProviderCard";
import { SttCard, TtsCard } from "./VoiceSection";

export function AgentSettings() {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const rulesRef = useRef<NotificationInterruptRulesHandle>(null);

  return (
    <div className="flex flex-col">
      <div className="pt-6 pb-2 flex items-center justify-center min-h-11 shrink-0">
        <h1 className="text-lg font-semibold">agent settings</h1>
      </div>

      <Tabs
        defaultValue="general"
        className="w-full max-w-[96rem] mx-auto pb-6"
      >
        <TabsList className="self-center">
          <TabsTrigger value="general">general</TabsTrigger>
          <TabsTrigger value="notifications">notifications</TabsTrigger>
          <TabsTrigger value="files">files</TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="mt-4">
          <div className="mx-auto grid w-full max-w-5xl gap-4 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
            <div
              className="flex flex-col gap-4 lg:sticky"
              style={{ top: navbarHeight + 16 }}
            >
              <ActionsCard />
            </div>
            <div className="flex min-w-0 flex-col gap-4">
              <ProviderCard />
              <SttCard />
              <TtsCard />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="notifications" className="mt-4">
          {/* Bento: a compact rules card beside the wider history it acts on. */}
          <div className="grid gap-4 xl:grid-cols-[33rem_minmax(0,1fr)] xl:items-start">
            <div className="flex flex-col gap-4">
              <NotificationInterruptRulesCard ref={rulesRef} />
              <DefaultRulesCard />
            </div>
            <NotificationsCard
              onMakeRule={(n) =>
                rulesRef.current?.addFromNotification({
                  source: n.source,
                  type: n.notif_type,
                })
              }
            />
          </div>
        </TabsContent>

        <TabsContent value="files" className="mt-4">
          <div className="mx-auto w-full max-w-5xl">
            <FilesTab />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
