import { useNavigate } from "react-router-dom";
import { Home } from "lucide-react";
import { AppSettings } from "@/components/Settings";
import { CheckForUpdates } from "@/components/CheckForUpdates";
import { LogoText } from "@/components/Logo/LogoText";
import { Navbar } from "@/components/Navbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { useLayout } from "@/stores/use-layout";

export function AppSettingsPage() {
  const navigate = useNavigate();
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <>
      <Navbar
        leading={
          <Button
            variant="outline"
            size="icon-lg"
            aria-label="home"
            onClick={() => navigate("/")}
          >
            <Home />
          </Button>
        }
        center={<LogoText />}
        trailing={
          <div className="flex items-center gap-2">
            <StatusPill showHostname={false} />
            <CheckForUpdates />
          </div>
        }
      />
      <div
        className="flex min-h-0 flex-1 flex-col px-page"
        style={{ paddingTop: navbarHeight }}
      >
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto pt-2">
          <div className="flex min-h-11 items-center justify-center py-6">
            <h1 className="text-lg font-semibold">app settings</h1>
          </div>
          <AppSettings />
        </div>
      </div>
    </>
  );
}
