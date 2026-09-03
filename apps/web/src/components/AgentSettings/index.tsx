import { useState } from "react";
import {
  Bell,
  Cpu,
  FolderClosed,
  Mic,
  ScrollText,
  Settings2,
  type LucideIcon,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageScroll } from "@/components/PageScroll";
import { useIsMobile } from "@/hooks/use-mobile";
import { useLayout } from "@/stores/use-layout";
import { cn } from "@/lib/utils";
import { ActionsCard } from "./ActionsCard";
import { BackupsCard } from "./BackupsCard";
import { ChatCard } from "./ChatCard";
import { DeleteCard } from "./DeleteCard";
import { NotificationInterruptRulesCard } from "./NotificationInterruptRulesCard";
import { NotificationsCard } from "./NotificationsCard";
import { RenameCard } from "./RenameCard";
import { FilesTab } from "./FilesTab";
import { LogsTab } from "./LogsTab";
import { ProviderCard } from "./ProviderCard";
import { ServicesCard } from "./ServicesCard";
import {
  ConversationCard,
  DictationCard,
  SttCard,
  TtsCard,
} from "./VoiceSection";

const NAV_ITEMS: { value: string; label: string; Icon: LucideIcon }[] = [
  { value: "general", label: "general", Icon: Settings2 },
  { value: "provider", label: "provider", Icon: Cpu },
  { value: "voice", label: "voice", Icon: Mic },
  { value: "notifications", label: "notifications", Icon: Bell },
  { value: "files", label: "files", Icon: FolderClosed },
  { value: "logs", label: "logs", Icon: ScrollText },
];

// Filled active item, no bar/shadow/ring; subtle fill on hover.
const NAV_ACTIVE =
  "hover:bg-accent/50 data-active:bg-accent data-active:text-accent-foreground data-active:shadow-none data-active:ring-0";

export function AgentSettings() {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const isMobile = useIsMobile();

  // Keep a tab mounted once visited so its fetched state survives tab switches,
  // while staying lazy: a tab isn't mounted until first opened.
  const [visited, setVisited] = useState<Set<string>>(
    () => new Set(["general"]),
  );
  const markVisited = (value: string) =>
    setVisited((prev) => (prev.has(value) ? prev : new Set(prev).add(value)));
  const keepAlive = (value: string): true | undefined =>
    visited.has(value) ? true : undefined;

  const panels = (
    <>
      <TabsContent
        value="general"
        forceMount={keepAlive("general")}
        className="flex flex-col gap-6 data-[state=inactive]:hidden max-md:pb-28"
      >
        <ActionsCard />
        <ChatCard />
        <ServicesCard />
        <BackupsCard />
        <RenameCard />
        <DeleteCard />
      </TabsContent>

      <TabsContent
        value="provider"
        forceMount={keepAlive("provider")}
        className="flex flex-col gap-6 data-[state=inactive]:hidden max-md:pb-28"
      >
        <ProviderCard />
      </TabsContent>

      <TabsContent
        value="voice"
        forceMount={keepAlive("voice")}
        className="flex flex-col gap-6 data-[state=inactive]:hidden max-md:pb-28"
      >
        <DictationCard />
        <ConversationCard />
        <SttCard />
        <TtsCard />
      </TabsContent>

      <TabsContent
        value="notifications"
        forceMount={keepAlive("notifications")}
        className="flex flex-col gap-6 data-[state=inactive]:hidden max-md:pb-28"
      >
        <NotificationInterruptRulesCard />
        <NotificationsCard />
      </TabsContent>

      <TabsContent
        value="files"
        forceMount={keepAlive("files")}
        className="data-[state=inactive]:hidden"
      >
        <FilesTab />
      </TabsContent>

      <TabsContent
        value="logs"
        forceMount={keepAlive("logs")}
        className="data-[state=inactive]:hidden"
      >
        <LogsTab />
      </TabsContent>
    </>
  );

  // One tree for both layouts (the nav chrome toggles, the content keeps a
  // stable key), so crossing the breakpoint never remounts the tabs and refetches.
  return (
    <Tabs
      orientation={isMobile ? "horizontal" : "vertical"}
      defaultValue="general"
      onValueChange={markVisited}
      className={cn(
        "relative flex min-h-0 w-full flex-1",
        isMobile && "flex-col",
      )}
    >
      <PageScroll
        contentClassName={cn(
          "flex w-full",
          !isMobile && "mx-auto max-w-[74rem] gap-0",
        )}
      >
        {/* Desktop: sticky sidebar hugging the content, with an equal-width
            spacer so the content stays centered and the spacer collapses first. */}
        {!isMobile && (
          <div
            key="sidebar"
            className="sticky w-52 shrink-0 self-start pr-8"
            style={{
              top: `calc(${String(navbarHeight)}px + var(--page-padding-x))`,
            }}
          >
            <Card size="sm" className="py-2.5">
              <TabsList className="w-full gap-0.5 bg-transparent p-0 px-2.5">
                {NAV_ITEMS.map(({ value, label, Icon }) => (
                  <TabsTrigger
                    key={value}
                    value={value}
                    className={`rounded-lg py-2 ${NAV_ACTIVE}`}
                  >
                    <Icon />
                    {label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Card>
          </div>
        )}

        <div
          key="content"
          className={cn("min-w-0", isMobile ? "w-full" : "w-[48rem]")}
        >
          {panels}
        </div>

        {!isMobile && (
          <div key="spacer" className="max-w-52 flex-1" aria-hidden />
        )}
      </PageScroll>

      {/* Mobile: a floating pill over the full-page scroll. */}
      {isMobile && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-4 pt-2 pb-[calc(1.75rem+env(safe-area-inset-bottom))]">
          <TabsList className="pointer-events-auto flex h-auto gap-1 rounded-3xl border border-border bg-popover p-1.5 shadow-md group-data-horizontal/tabs:h-auto">
            {NAV_ITEMS.map(({ value, label, Icon }) => (
              <TabsTrigger
                key={value}
                value={value}
                className={`flex h-auto min-w-16 flex-none flex-col gap-1 rounded-2xl px-2 py-2 text-[10px] leading-tight ${NAV_ACTIVE}`}
              >
                <Icon className="size-5" />
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      )}
    </Tabs>
  );
}
