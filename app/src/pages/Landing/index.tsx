import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/AuthProvider";
const INSTALL_UNIX = "curl -fsSL https://vesta.run/install.sh | bash";
const INSTALL_WINDOWS = "irm https://vesta.run/install.ps1 | iex";
function getInstallCmd(): string {
  return navigator.platform?.startsWith("Win") ? INSTALL_WINDOWS : INSTALL_UNIX;
}

function getOsName(): string {
  const p = navigator.platform ?? "";
  if (p.startsWith("Win")) return "Windows";
  if (p.startsWith("Mac")) return "macOS";
  if (p.includes("Linux")) return "Linux";
  return "your OS";
}

export function Landing() {
  const { initialized, connected } = useAuth();
  const [copied, setCopied] = useState(false);
  const installCmd = getInstallCmd();
  const osName = getOsName();

  if (initialized && connected) return <Navigate to="/home" replace />;

  const copy = async () => {
    await navigator.clipboard.writeText(installCmd);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col items-center justify-center flex-1 min-h-0 px-4 gap-5 select-none">
      <div className="flex flex-col items-center gap-8">
        <div className="flex flex-col items-center gap-1">
          <h1 className="text-4xl font-serif font-medium tracking-tight">
            Vesta
          </h1>
          <p className="text-sm text-muted-foreground">Your personal assistant</p>
        </div>

        <div className="relative">
          <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 z-10 rounded-md border border-border bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground">Download now for {osName}</span>
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-4 py-2.5 pt-3.5">
            <code className="text-sm font-mono text-foreground select-all">
              {installCmd}
            </code>
          <Button
            variant="ghost"
            size="icon"
            className="size-7 shrink-0"
            onClick={copy}
          >
            {copied ? <Check /> : <Copy />}
          </Button>
          </div>
        </div>
      </div>

      <Button size="sm" asChild>
        <Link to="/home">Continue in browser</Link>
      </Button>
    </div>
  );
}
