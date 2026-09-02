import { useNavigate } from "react-router-dom";
import { Home } from "lucide-react";
import { AppSettings } from "@/components/Settings";
import { WhatsNewButton } from "@/components/WhatsNew";
import { NavbarLogoText } from "@/components/Logo/LogoText";
import { Navbar } from "@/components/Navbar";
import { PageScroll } from "@/components/PageScroll";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";

export function AppSettingsPage() {
  const navigate = useNavigate();

  return (
    <>
      <Navbar
        leading={
          <Button
            variant="outline"
            size="icon-lg"
            aria-label="home"
            onClick={() => {
              void navigate("/");
            }}
          >
            <Home />
          </Button>
        }
        center={<NavbarLogoText />}
        trailing={
          <div className="flex items-center gap-2">
            <StatusPill showHostname={false} />
            <WhatsNewButton />
          </div>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col">
        <PageScroll>
          <AppSettings />
        </PageScroll>
      </div>
    </>
  );
}
