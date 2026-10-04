import { useState } from "react";
import { Download, ExternalLink, Monitor, Smartphone } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { MenuSection } from "@/components/ui/menu-section";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/Dialog";
import { runtimeInfo } from "@/lib/native";
import { cn } from "@/lib/utils";
import {
  ANDROID_DOWNLOAD,
  computerDownloads,
  otherVersionsUrl,
  type AppDownload,
} from "./app-downloads";

// Browser only: inside the desktop app the user already has it, and it updates itself.
const { isDesktopApp, platform } = runtimeInfo;

export function GetAppsCard() {
  if (isDesktopApp) return null;
  return (
    <Card size="sm" className="md:col-span-2">
      <CardContent>
        <AppDownloads sectionsClassName="md:grid-cols-2" />
      </CardContent>
    </Card>
  );
}

export function GetAppsLink() {
  const [open, setOpen] = useState(false);
  if (isDesktopApp) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mx-auto px-3 py-3 text-xs text-muted-foreground underline-offset-4 hover:underline"
      >
        get the Vesta app
      </button>
      <Dialog open={open} onOpenChange={setOpen} drawerOnMobile>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>get the Vesta app</DialogTitle>
            <DialogDescription>
              keep Vesta with you on your computer and your phone
            </DialogDescription>
          </DialogHeader>
          <AppDownloads />
        </DialogContent>
      </Dialog>
    </>
  );
}

function AppDownloads({ sectionsClassName }: { sectionsClassName?: string }) {
  return (
    <div className="flex flex-col gap-4">
      <div className={cn("grid gap-4", sectionsClassName)}>
        <MenuSection title="computer">
          <div className="mt-1 flex flex-col gap-2">
            {computerDownloads(__APP_VERSION__).map((download) => (
              <DownloadRow
                key={download.url}
                icon={Monitor}
                download={download}
              />
            ))}
          </div>
        </MenuSection>
        <MenuSection title="phone">
          <div className="mt-1 flex flex-col gap-2">
            <DownloadRow icon={Smartphone} download={ANDROID_DOWNLOAD} />
            <Button variant="outline" disabled className="w-full justify-start">
              <Smartphone data-icon="inline-start" />
              iPhone
              <span className="ml-auto text-muted-foreground">coming soon</span>
            </Button>
          </div>
        </MenuSection>
      </div>
      <a
        href={otherVersionsUrl(__APP_VERSION__)}
        target="_blank"
        rel="noreferrer"
        className="mx-auto flex items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:underline"
      >
        other versions
        <ExternalLink className="size-3" />
      </a>
    </div>
  );
}

function DownloadRow({
  icon: Icon,
  download,
}: {
  icon: LucideIcon;
  download: AppDownload;
}) {
  // The visitor's own device stands out, so most people never read the rest of the list.
  const ownDevice = download.platform === platform;
  return (
    <Button
      asChild
      variant={ownDevice ? "default" : "outline"}
      className="w-full justify-start"
    >
      <a href={download.url}>
        <Icon data-icon="inline-start" />
        {download.name}
        {download.hint && <span className="opacity-60">{download.hint}</span>}
        <Download data-icon="inline-end" className="ml-auto" />
      </a>
    </Button>
  );
}
