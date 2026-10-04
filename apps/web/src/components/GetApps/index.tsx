import type { ComponentType } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { MenuSection } from "@/components/ui/menu-section";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/DropdownMenu";
import { runtimeInfo } from "@/lib/native";
import type { Platform } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { appTiles, type AppTile } from "./app-downloads";
import { AndroidLogo, AppleLogo, LinuxLogo, WindowsLogo } from "./logos";

// Browser only: inside the desktop app the user already has it, and it updates itself.
const { isDesktopApp, platform } = runtimeInfo;

const LOGOS: Record<Platform, ComponentType<{ className?: string }>> = {
  macos: AppleLogo,
  windows: WindowsLogo,
  linux: LinuxLogo,
  android: AndroidLogo,
  ios: AppleLogo,
};

const TILE_CLASS =
  "flex aspect-square w-full flex-col items-center justify-center gap-2 rounded-squircle-sm [corner-shape:squircle] bg-foreground/5 text-xs font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/30";

export function GetAppsCard() {
  if (isDesktopApp) return null;
  return (
    <Card size="sm">
      <CardContent>
        <MenuSection title="get the Vesta app">
          <AppTiles className="mt-2" />
        </MenuSection>
      </CardContent>
    </Card>
  );
}

export function GetAppsRow() {
  if (isDesktopApp) return null;
  return (
    <div className="mx-auto flex w-full max-w-[27rem] flex-col items-center gap-2">
      <p className="text-xs text-muted-foreground">get the Vesta app</p>
      <AppTiles />
    </div>
  );
}

function AppTiles({ className }: { className?: string }) {
  return (
    <div className={cn("grid w-full grid-cols-5 gap-3", className)}>
      {appTiles(__APP_VERSION__).map((tile) => (
        <Tile key={tile.platform} tile={tile} />
      ))}
    </div>
  );
}

function Tile({ tile }: { tile: AppTile }) {
  const Logo = LOGOS[tile.platform];
  // The visitor's own device stands out, so most people never read the rest of the row.
  const ownDevice = tile.platform === platform;
  const face = (
    <>
      <Logo className="size-7" />
      <span className="flex flex-col items-center gap-1 leading-none">
        {tile.name}
        {tile.choices.length === 0 && (
          <span className="text-[0.625rem] whitespace-nowrap text-muted-foreground">
            soon
          </span>
        )}
      </span>
    </>
  );
  const className = cn(
    TILE_CLASS,
    ownDevice && "ring-1 ring-primary",
    tile.choices.length > 0 ? "hover:bg-foreground/10" : "opacity-50",
  );
  const [only, ...rest] = tile.choices;

  if (only === undefined) return <div className={className}>{face}</div>;
  if (rest.length === 0) {
    return (
      <a href={only.url} title={tile.hint ?? undefined} className={className}>
        {face}
      </a>
    );
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className={className}>{face}</DropdownMenuTrigger>
      <DropdownMenuContent>
        {tile.choices.map((choice) => (
          <DropdownMenuItem key={choice.url} asChild>
            <a href={choice.url}>{choice.label}</a>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
