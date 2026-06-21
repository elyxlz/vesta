import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { AppSettings } from "@/components/Settings";
import { CheckForUpdates } from "@/components/CheckForUpdates";
import { Footer } from "@/components/Footer";
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
            aria-label="back"
            onClick={() => navigate(-1)}
          >
            <ArrowLeft />
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
        className="flex flex-1 flex-col overflow-y-auto px-page pb-8"
        style={{ paddingTop: navbarHeight }}
      >
        <AppSettings />
      </div>
      <Footer />
    </>
  );
}
