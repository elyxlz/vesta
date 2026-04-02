import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { connectToServer } from "@/api";
import { useAppStore } from "@/stores/use-app-store";
import { useNavigation } from "@/stores/use-navigation";

export function Connect() {
  const setView = useNavigation((s) => s.setView);
  const setConnected = useAppStore((s) => s.setConnected);

  const [host, setHost] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const [details, setDetails] = useState("");
  const [showDetails, setShowDetails] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleConnect = useCallback(async () => {
    if (!host.trim() || !apiKey.trim() || busy) return;
    setBusy(true);
    setError("");
    setDetails("");

    try {
      const url = host.includes("://") ? host.trim() : `https://${host.trim()}`;
      await connectToServer(url, apiKey.trim());
      setConnected(true);
      setView("home");
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message || "connection failed";
      if (msg === "could not reach server") {
        setError("could not reach server");
      } else {
        setError("could not reach server");
        setDetails(msg);
      }
    } finally {
      setBusy(false);
    }
  }, [host, apiKey, busy, setConnected, setView]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") handleConnect();
    },
    [handleConnect],
  );

  return (
    <div className="flex flex-col items-center justify-center h-full animate-view-in">
      <div className="flex flex-col items-center gap-4 w-full max-w-[240px] px-4">
        <div className="text-center mb-2">
          <h1 className="text-[15px] font-semibold text-foreground">connect</h1>
          <p className="text-[11px] text-muted mt-1">
            connect to a remote vesta server.
          </p>
        </div>

        <Input
          placeholder="host:port"
          value={host}
          onChange={(e) => setHost(e.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
          className="text-center text-[13px]"
        />

        <Input
          type="password"
          placeholder="API key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          onKeyDown={handleKeyDown}
          className="text-center text-[13px]"
        />

        <Button
          onClick={handleConnect}
          disabled={!host.trim() || !apiKey.trim() || busy}
          className="w-full"
          size="sm"
        >
          {busy ? "connecting..." : "connect"}
        </Button>

        {error && (
          <div className="text-center animate-shake">
            <p className="text-[11px] text-destructive">{error}</p>
            {details && (
              <>
                <button
                  onClick={() => setShowDetails(!showDetails)}
                  className="text-[10px] text-muted hover:text-foreground mt-1"
                >
                  {showDetails ? "hide details" : "show details"}
                </button>
                {showDetails && (
                  <p className="text-[10px] text-muted mt-1 break-all">
                    {details}
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
