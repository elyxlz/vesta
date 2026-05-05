import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ActionsCard } from "./ActionsCard";
import { FilesTab } from "./FilesTab";
import { KeybindsCard } from "./KeybindsSection";
import { PlanUsage } from "./PlanUsage";
import { SttCard, TtsCard } from "./VoiceSection";

export function AgentSettings() {
  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-y-auto pt-2">
      <div className="py-6 flex items-center justify-center min-h-11">
        <h1 className="text-lg font-semibold">agent settings</h1>
      </div>

      <Tabs defaultValue="general" className="w-full max-w-5xl mx-auto pb-6">
        <TabsList className="self-center">
          <TabsTrigger value="general">general</TabsTrigger>
          <TabsTrigger value="files">files</TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="mt-4">
          <div className="grid w-full gap-4 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
            <div className="flex flex-col gap-4 lg:sticky lg:top-6">
              <ActionsCard />
              <KeybindsCard />
            </div>
            <div className="flex min-w-0 flex-col gap-4">
              <PlanUsage />
              <SttCard />
              <TtsCard />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="files" className="mt-4">
          <FilesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
